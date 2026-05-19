## 오늘의 요약

Root 계정이 MFA 없이 활성 액세스 키를 사용하고 있으며, 최근 콘솔 로그인이 감지되어 보안상 매우 위험한 상황입니다. CloudTrail에서 dave 사용자가 main-trail을 삭제하는 등 민감한 활동이 발견되었고, 백업 작업 2건이 KMS 권한 부족과 DB 수정 중 충돌로 실패했습니다. 또한 1,120GB의 미연결 볼륨과 3개의 미할당 EIP로 인한 불필요한 비용이 발생하고 있습니다.

## 즉시 조치 필요

- **[긴급]** Root 계정 보안 강화 — MFA가 비활성화되고 액세스 키가 활성 상태로 2026-05-18에 사용됨. 즉시 MFA 활성화 및 액세스 키 비활성화 필요
- **[높음]** CloudTrail 삭제 사고 대응 — dave 사용자가 2026-05-18T10:22:00에 main-trail을 삭제함. 감사 로그 복구 및 권한 재검토 필요
- **[높음]** 백업 실패 해결 — i-0aaa1116 인스턴스와 fnf-stg-db의 백업이 KMS 권한 부족과 DB 수정 충돌로 실패. 권한 설정 및 백업 스케줄 조정 필요

## 참고 사항

- **비용 최적화**: 미연결 EBS 볼륨 6개(총 1,120GB)와 미할당 EIP 3개(52.78.123.1, 52.78.123.2, 52.78.123.3) 정리로 월 비용 절감 가능
- **IAM 위생**: alice, bob, dave 사용자가 콘솔 MFA 미설정 상태이며, deploy-bot과 data-export 등 4개 계정의 액세스 키가 90일 이상 미사용 또는 미순환
- **S3 보안**: legacy-static-site와 shared-uploads 버킷이 퍼블릭 액세스 차단 미설정, legacy-static-site와 fnf-temp-import 버킷이 기본 암호화 미적용 상태
---USAGE--- {'inputTokens': 2751, 'outputTokens': 726, 'totalTokens': 3477, 'cacheReadInputTokens': 0, 'cacheWriteInputTokens': 0}
