import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel("INFO")

REGION = os.environ["AWS_REGION"]
MODEL_ID = os.environ.get(
    "MODEL_ID", "apac.anthropic.claude-sonnet-4-20250514-v1:0"
)
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1500"))

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


def handler(event, context):
    sections = event.get("sections") or []
    prompt = PROMPT_TEMPLATE.format(
        sections=json.dumps(sections, ensure_ascii=False)
    )

    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        resp = client.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage") or {}
        return {
            "summary_md": text,
            "tokens": {
                "input": usage.get("inputTokens", 0),
                "output": usage.get("outputTokens", 0),
            },
            "model_id": MODEL_ID,
            "error": None,
        }
    except ClientError as e:
        logger.warning("bedrock invoke failed: %s", e)
        return {
            "summary_md": "",
            "tokens": {"input": 0, "output": 0},
            "model_id": MODEL_ID,
            "error": str(e.response.get("Error", {}).get("Code") or e),
        }
