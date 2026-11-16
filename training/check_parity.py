"""언어 간 예측 일치(parity) 검사. CI 에서 실패(exit 1)하면 이후 단계가 진행되지 않는다.

기준은 학습한 원본 모델(MODEL_IMPL=sklearn)로 띄운 Python API 이고,
Go/Rust 등 다른 언어로 옮긴 서비스가 같은 입력에 같은 값을 내는지 비교한다.

서버가 떠 있어야 하므로 pytest 테스트가 아니다. 표준 라이브러리만 쓴다.

실행
  python -m training.check_parity

환경 변수
  PY_URL   기준 Python API 주소 (기본 http://127.0.0.1:8080)
  TARGETS  비교 대상 "이름=주소" 쉼표 목록
           (기본 go=http://127.0.0.1:8081,rust=http://127.0.0.1:8082)

통과 조건
  대상마다 모든 입력에서 |대상 - 기준| 의 최대값 < TOLERANCE 분
"""
import json
import os
import random
import sys
import urllib.error
import urllib.request

TOLERANCE = 1e-4  # 분
TIMEOUT = 5.0     # 초
PY_URL = os.getenv("PY_URL", "http://127.0.0.1:8080")
TARGETS = os.getenv("TARGETS", "go=http://127.0.0.1:8081,rust=http://127.0.0.1:8082")


def parse_targets(spec: str) -> dict[str, str]:
    """'go=http://...,rust=http://...' 를 {이름: 주소} 로 바꾼다."""
    targets = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, url = item.partition("=")
        if not sep or not name.strip() or not url.strip():
            raise SystemExit(f"TARGETS 형식이 잘못됐다: {item!r} (이름=주소 형태여야 한다)")
        targets[name.strip()] = url.strip()
    if not targets:
        raise SystemExit("TARGETS 가 비어 있다")
    return targets


def make_cases(n_random: int = 20, seed: int = 0) -> list[tuple[float, int]]:
    """고정 입력 3건 + seed 로 뽑은 무작위 입력. 같은 seed 면 항상 같은 입력이 나온다."""
    cases = [(3.0, 2), (0.0, 0), (8.0, 10)]
    rng = random.Random(seed)
    for _ in range(n_random):
        cases.append((rng.uniform(0.5, 8.0), rng.randint(0, 10)))
    return cases


def predict(base_url: str, distance_km: float, pending_orders: int) -> float:
    """POST /eta 를 호출해 minutes 를 돌려준다. 실패하면 RuntimeError."""
    body = json.dumps({"distance_km": distance_km, "pending_orders": pending_orders}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/eta",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return float(json.load(resp)["minutes"])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"연결 실패: {e}") from e
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"응답 형식 오류: {e}") from e


def main() -> int:
    targets = parse_targets(TARGETS)
    cases = make_cases()

    try:
        expected = [predict(PY_URL, d, o) for d, o in cases]
    except RuntimeError as e:
        print(f"FAIL [python] 기준 서버 {PY_URL} 호출 실패: {e}")
        return 1

    all_ok = True
    for name, url in targets.items():
        try:
            got = [predict(url, d, o) for d, o in cases]
        except RuntimeError as e:
            print(f"FAIL [{name}] {url} 호출 실패: {e}")
            all_ok = False
            continue

        diffs = [abs(g - e) for g, e in zip(got, expected)]
        worst = max(range(len(diffs)), key=diffs.__getitem__)
        max_diff = diffs[worst]
        ok = max_diff < TOLERANCE
        all_ok &= ok
        d, o = cases[worst]
        print(
            ("PASS " if ok else "FAIL ")
            + f"[{name}] 최대 오차 {max_diff:.3e}분 {'<' if ok else '>='} {TOLERANCE:g}분 ({len(cases)}건, "
            + f"최악 입력 distance_km={d:.4f}, pending_orders={o}: "
            + f"{name}={got[worst]:.6f}, python={expected[worst]:.6f})"
        )

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
