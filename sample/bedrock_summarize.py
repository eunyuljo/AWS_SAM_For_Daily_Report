"""
Bedrock 요약 검증 스크립트.

운영 코드와 무관한 일회성 PoC. sample/demo_payload.json 또는 S3에서 받은
실제 sections JSON을 입력으로 받아 Claude에 요약을 요청한다.

사용:
    python3 sample/bedrock_summarize.py sample/demo_payload.json

요구:
    - boto3
    - bedrock:InvokeModel 권한
    - 서울 리전(ap-northeast-2) 기준 inference profile 사용

서울 리전에서 사용 가능한 inference profile (2026-05 기준):
    apac.anthropic.claude-sonnet-4-20250514-v1:0  (현재 사용)
    apac.anthropic.claude-3-5-sonnet-20241022-v2:0
    apac.anthropic.claude-3-haiku-20240307-v1:0
"""
import json
import sys

import boto3

REGION = "ap-northeast-2"
MODEL_ID = "apac.anthropic.claude-sonnet-4-20250514-v1:0"

PROMPT_TEMPLATE = """당신은 AWS MSP 운영 분석가입니다. 아래 JSON은 AWS 계정 일일 점검 결과입니다.

규칙:
- JSON에 있는 숫자/리소스 ID만 인용하세요. 새로 만들지 마세요.
- 추측하지 말고 데이터에서 확실한 것만 말하세요.
- 한국어 존댓말로 답하세요.
- HTML이 아닌 마크다운으로 응답하세요.

다음 형식으로 답하세요:

## 오늘의 요약
3-4문장으로 가장 중요한 변화/위험을 임원이 읽기 좋게 정리.

## 즉시 조치 필요 (최대 3개)
- **[심각도]** 항목명 — 왜 위험한가, 무엇을 해야 하는가

## 참고 사항 (최대 3개)
- 추세, 패턴, 미사용 자원 등

JSON 데이터:
{sections}
"""


def main(payload_path: str) -> None:
    with open(payload_path) as f:
        sections = json.load(f)["sections"]

    prompt = PROMPT_TEMPLATE.format(sections=json.dumps(sections, ensure_ascii=False))

    client = boto3.client("bedrock-runtime", region_name=REGION)
    resp = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1500, "temperature": 0.0},
    )
    print(resp["output"]["message"]["content"][0]["text"])
    print("\n---USAGE---", resp.get("usage"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: bedrock_summarize.py <sections_payload.json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
