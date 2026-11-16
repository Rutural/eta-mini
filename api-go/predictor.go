package main

import (
	"fmt"

	ort "github.com/yalue/onnxruntime_go"
)

// Predictor 는 ONNX 모델 세션을 들고 있다. ONNX Runtime 의 Run 은 동시 호출에 안전하다.
type Predictor struct {
	session *ort.DynamicAdvancedSession
}

func NewPredictor(libPath, modelPath string) (*Predictor, error) {
	ort.SetSharedLibraryPath(libPath)
	if err := ort.InitializeEnvironment(); err != nil {
		return nil, fmt.Errorf("ONNX Runtime 초기화: %w", err)
	}
	s, err := ort.NewDynamicAdvancedSession(modelPath, []string{"X"}, []string{"variable"}, nil)
	if err != nil {
		_ = ort.DestroyEnvironment()
		return nil, fmt.Errorf("세션 생성 (%s): %w", modelPath, err)
	}
	return &Predictor{session: s}, nil
}

// Estimate 는 배달 예상 시간(분)을 계산한다. 입력은 Python 구현과 같이 float32 로 바꿔 넣는다.
func (p *Predictor) Estimate(distanceKm, pendingOrders float64) (float64, error) {
	input, err := ort.NewTensor(ort.NewShape(1, 2), []float32{float32(distanceKm), float32(pendingOrders)})
	if err != nil {
		return 0, err
	}
	defer input.Destroy()

	outputs := []ort.Value{nil} // 출력은 ONNX Runtime 이 할당한다
	if err := p.session.Run([]ort.Value{input}, outputs); err != nil {
		return 0, err
	}
	defer outputs[0].Destroy()

	out, ok := outputs[0].(*ort.Tensor[float32])
	if !ok {
		return 0, fmt.Errorf("예상하지 못한 출력 타입 %T", outputs[0])
	}
	data := out.GetData()
	if len(data) == 0 {
		return 0, fmt.Errorf("빈 출력")
	}
	return float64(data[0]), nil
}

func (p *Predictor) Close() {
	_ = p.session.Destroy()
	_ = ort.DestroyEnvironment()
}
