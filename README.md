# AWS MSP Daily Report

Step Functions로 매일 09:00 KST에 인프라 상태를 수집해 HTML 리포트를 S3에 저장하고 presigned URL을 반환합니다.

## 아키텍처

```
EventBridge Schedule (09:00 KST)
        ↓
Step Functions (STANDARD)
  ├─ Parallel Collect
  │    ├─ ec2_rds         (EC2/RDS 인벤토리, 미사용 EBS·EIP)
  │    ├─ iam_hygiene     (루트 MFA/키, 사용자 MFA, 90일+ 미사용 키)
  │    ├─ cloudtrail_risk (루트 콘솔 로그인, SG 0.0.0.0/0, IAM 변경 등)
  │    ├─ s3_hygiene      (퍼블릭 차단/암호화 미설정 버킷)
  │    └─ backup_status   (AWS Backup 작업/보호 리소스)
  ├─ Summarize            (Bedrock Claude 요약 - HIGH 빈도 finding 자연어 분석)
  ├─ Render               (HTML 생성, 상단에 AI 요약 삽입)
  └─ Publish              (S3 업로드 + presigned URL)
```

각 collector는 자기 단계 실패 시에도 다른 단계는 진행 가능하도록 `Catch`로 감싸 Pass State에 떨어트립니다.

## 구조

```
.
├── template.yaml                       # Lambda 6 + SFN + Schedule + S3 Bucket
├── samconfig.toml                      # dev/prod 배포 프로파일
├── statemachine/
│   └── daily_report.asl.json           # Parallel → Render → Publish
├── src/functions/
│   ├── ec2_rds/         app.py
│   ├── iam_hygiene/     app.py
│   ├── cloudtrail_risk/ app.py
│   ├── s3_hygiene/      app.py
│   ├── render/          app.py
│   └── publish/         app.py
└── events/start.json
```

## IAM 권한 (계정 단위, 추가 세팅 불필요)

| Function | API |
|---|---|
| ec2_rds | ec2:DescribeInstances/Volumes/Addresses, rds:DescribeDBInstances |
| iam_hygiene | iam:GenerateCredentialReport, iam:GetCredentialReport |
| cloudtrail_risk | cloudtrail:LookupEvents |
| s3_hygiene | s3:ListAllMyBuckets, s3:GetBucketPublicAccessBlock, s3:GetEncryptionConfiguration |
| publish | s3:PutObject (ReportsBucket 한정) |
| summarize | bedrock:InvokeModel (Claude Sonnet 4 inference profile 한정) |

> 첫 배포 전 **Bedrock 콘솔 → Model access**에서 `Claude Sonnet 4` 활성화 필요. 미활성 시 Summarize는 fallback(빈 요약)으로 graceful skip되어 보고서는 정상 생성됩니다.
>
> **비용**: Bedrock 1회 호출 약 $0.01~0.02 (입력 3K / 출력 1K 토큰 기준). 일 1회 자동 실행 → 월 약 $0.5.

## 사전 준비

```bash
pip install --user aws-sam-cli
sam --version
aws sts get-caller-identity
```

## 배포

```bash
sam validate --lint
sam build
sam deploy --config-env default          # dev
sam deploy --config-env prod             # prod (확인 프롬프트 있음)
```

## 빠른 반복 개발

```bash
sam sync --watch --config-env default
```

## 로컬 실행 (개별 collector)

```bash
sam local invoke Ec2RdsFunction         --event events/start.json
sam local invoke IamHygieneFunction     --event events/start.json
sam local invoke CloudTrailRiskFunction --event events/start.json
sam local invoke S3HygieneFunction      --event events/start.json
```

> `sam local invoke`는 호스트 AWS 자격증명을 그대로 컨테이너에 주입합니다.

## 배포 후 수동 실행

```bash
ARN=$(aws cloudformation describe-stacks \
  --stack-name daily-report-dev \
  --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
  --output text)

aws stepfunctions start-execution \
  --state-machine-arn "$ARN" \
  --input '{}'
```

실행 출력의 `output` 필드에 `{ "bucket": "...", "key": "reports/2026-05-19.html", "url": "https://..." }` 형태로 presigned URL이 들어 있습니다 (TTL 7일).

## 산출물 위치

- 버킷: `daily-report-{AccountId}-{Region}-{Env}` (퍼블릭 차단 + AES256 + 90일 라이프사이클)
- HTML: `reports/YYYY-MM-DD.html` — 사람이 보는 보고서 (presigned URL로 공유)
- JSON: `reports/YYYY-MM-DD.json` — 원본 메트릭 (다음 날 전일 대비 비교에 사용, BI 연동 가능)

## 브랜딩/표시 항목 커스터마이즈

`template.yaml` 파라미터:

| Parameter | Default | 의미 |
|---|---|---|
| `MspName` | MegazoneCloud | 헤더 좌측 MSP 이름 |
| `CustomerName` | FNF | 헤더 우측 고객사명 |
| `BrandColor` | #1B69D6 | 헤더/제목/배지 강조색 |
| `LogoUrl` | https://start.megazone.com/.../og-megazone-pops.png | 헤더 좌측 로고 이미지 URL (빈 값이면 숨김) |

배포 시 `--parameter-overrides`로 덮어쓰기:

```bash
sam deploy --config-env default \
  --parameter-overrides "Env=dev MspName=MegazoneCloud CustomerName=FNF BrandColor=#1B69D6"
```

리포트 내 표현 조정:
- 요약 카드 항목: `src/functions/render/app.py`의 `_section_summary` 안의 `cards` 리스트
- 심각도 규칙: 같은 파일 `_severity` 함수 (CRITICAL/HIGH/MEDIUM/LOW 분기)
- 위험 이벤트 종류: `src/functions/cloudtrail_risk/app.py`의 `RISK_EVENTS`
- 미사용 키 임계값: `src/functions/iam_hygiene/app.py`의 `STALE_KEY_DAYS`

## 정리

```bash
sam delete --config-env default
# ReportsBucket은 DeletionPolicy: Retain — 필요 시 수동 삭제
```

## 다음 단계

- **Slack 알림 추가**: `Publish` 다음 `Notify` State 추가, presigned URL을 incoming webhook에 POST
- **AWS Backup 백업 결과**: collector 추가 (`backup:ListBackupJobs`)
- **멀티계정 확장**: payer 계정에서 cross-account role assume 후 `Map` State로 fan-out
- **에러 알림**: SFN 실행 실패 시 EventBridge 룰로 SNS 통지
