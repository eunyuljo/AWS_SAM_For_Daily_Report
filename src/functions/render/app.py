import html
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel("INFO")

ACCOUNT = os.environ.get("ACCOUNT_ID", "")
ENV = os.environ.get("ENV", "dev")
MSP_NAME = os.environ.get("MSP_NAME", "MSP")
CUSTOMER = os.environ.get("CUSTOMER_NAME", "")
BRAND = os.environ.get("BRAND_COLOR", "#1B69D6")
LOGO_URL = os.environ.get("LOGO_URL", "")
BUCKET = os.environ.get("REPORTS_BUCKET", "")


def _esc(value):
    return html.escape(str(value), quote=True)


def _load_prev_metrics():
    if not BUCKET:
        return None
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    key = f"reports/{yesterday}.json"
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        data = json.loads(obj["Body"].read())
        return data.get("metrics", {})
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
            return None
        logger.warning("prev metrics load failed: %s", e)
        return None


def _load_history_metrics(days=7):
    if not BUCKET:
        return {}
    s3 = boto3.client("s3")
    series = {}
    today = datetime.now(timezone.utc)
    for offset in range(days, 0, -1):
        d = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        try:
            obj = s3.get_object(Bucket=BUCKET, Key=f"reports/{d}.json")
            metrics = json.loads(obj["Body"].read()).get("metrics", {}) or {}
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "AccessDenied"):
                continue
            logger.warning("history load failed for %s: %s", d, e)
            continue
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                series.setdefault(k, []).append(v)
    return series


def _bar_chart(title, items, value_suffix=""):
    items = [(label, val) for label, val in items if val and val > 0]
    if not items:
        return ""
    max_val = max(v for _, v in items) or 1
    rows = "".join(
        f'<li>'
        f'<span class="bar-label">{_esc(label)}</span>'
        f'<span class="bar-track"><span class="bar-fill" '
        f'style="width:{(v / max_val) * 100:.1f}%"></span></span>'
        f'<span class="bar-value">{v}{value_suffix}</span>'
        f'</li>'
        for label, v in items
    )
    return f"""
    <div class="bar-chart">
      <div class="bar-title">{_esc(title)}</div>
      <ul class="bars">{rows}</ul>
    </div>
    """


def _timeline_24h(events, time_key="time"):
    if not events:
        return ""
    width, height = 720, 60
    pad_l, pad_r, pad_t, pad_b = 32, 16, 16, 22
    inner_w = width - pad_l - pad_r
    base_y = height - pad_b
    points = []
    for ev in events:
        ts = ev.get(time_key)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        kst_hour = (dt.astimezone(timezone(timedelta(hours=9)))
                    .hour
                    + dt.astimezone(timezone(timedelta(hours=9))).minute / 60.0)
        x = pad_l + (kst_hour / 24.0) * inner_w
        points.append((x, ev))
    if not points:
        return ""

    ticks = "".join(
        f'<line x1="{pad_l + (h / 24.0) * inner_w:.1f}" x2="{pad_l + (h / 24.0) * inner_w:.1f}" '
        f'y1="{base_y - 4}" y2="{base_y + 4}" stroke="#9AA1AD" stroke-width="1"/>'
        f'<text x="{pad_l + (h / 24.0) * inner_w:.1f}" y="{base_y + 16}" '
        f'text-anchor="middle" font-size="10" fill="#6B7280">{h:02d}</text>'
        for h in range(0, 25, 4)
    )

    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{base_y - 12}" r="4" '
        f'fill="#E60012" fill-opacity="0.75">'
        f'<title>{_esc((ev.get(time_key) or "")[:19])} · {_esc(ev.get("event_name") or "")}'
        f' ({_esc(ev.get("user") or "-")})</title>'
        f'</circle>'
        for x, ev in points
    )

    return f"""
    <div class="timeline">
      <div class="timeline-title">시간대별 분포 (KST)</div>
      <svg viewBox="0 0 {width} {height}" role="img"
           aria-label="24시간 위험 이벤트 타임라인">
        <line x1="{pad_l}" x2="{width - pad_r}" y1="{base_y}" y2="{base_y}"
              stroke="#D4D4DA" stroke-width="1"/>
        {ticks}
        {dots}
      </svg>
    </div>
    """


def _donut(title, items):
    items = [(label, int(val), color) for label, val, color in items if val and val > 0]
    if not items:
        return f"""
        <div class="donut-card">
          <div class="donut-title">{_esc(title)}</div>
          <p class="summary-note">데이터 없음</p>
        </div>
        """
    total = sum(v for _, v, _ in items)
    size, stroke = 120, 18
    radius = (size - stroke) / 2
    cx = cy = size / 2
    circumference = 2 * 3.141592653589793 * radius
    offset = 0.0
    rings = []
    for _, v, color in items:
        portion = v / total
        dash = circumference * portion
        rings.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius:.2f}" '
            f'fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash

    legend_rows = "".join(
        f'<li><span class="legend-swatch" style="background:{color}"></span>'
        f'<span class="legend-label">{_esc(label)}</span>'
        f'<span class="legend-value">{v} ({v / total * 100:.0f}%)</span></li>'
        for label, v, color in items
    )

    return f"""
    <div class="donut-card">
      <div class="donut-title">{_esc(title)}</div>
      <div class="donut-body">
        <svg class="donut" viewBox="0 0 {size} {size}" role="img"
             aria-label="{_esc(title)} 분포">
          <title>{_esc(title)} (총 {total})</title>
          {''.join(rings)}
          <text x="{cx}" y="{cy - 2}" text-anchor="middle"
                font-size="20" font-weight="700" fill="#1F2430">{total}</text>
          <text x="{cx}" y="{cy + 14}" text-anchor="middle"
                font-size="10" fill="#6B7280">total</text>
        </svg>
        <ul class="legend">{legend_rows}</ul>
      </div>
    </div>
    """


def _sparkline(history, curr):
    if history is None:
        history = []
    points = list(history) + [curr]
    if len(points) < 2:
        return ""
    width, height, pad = 80, 24, 2
    lo, hi = min(points), max(points)
    span = hi - lo or 1
    n = len(points)
    coords = []
    for i, v in enumerate(points):
        x = pad + (i / (n - 1)) * (width - 2 * pad)
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        coords.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = coords[-1].split(",")
    series_label = " → ".join(str(p) for p in points)
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'role="img" aria-label="최근 7일 추이">'
        f'<title>최근 7일 추이: {series_label}</title>'
        f'<polyline fill="none" stroke="currentColor" stroke-width="1.4" '
        f'points="{" ".join(coords)}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="1.8" fill="currentColor"/>'
        f"</svg>"
    )


def _delta_str(curr, prev):
    if prev is None:
        return ""
    diff = curr - prev
    if diff == 0:
        return '<span class="d-zero">±0</span>'
    sign = "+" if diff > 0 else ""
    cls = "d-up" if diff > 0 else "d-down"
    return f'<span class="{cls}">{sign}{diff}</span>'


def _compute_metrics(by_section):
    ec2 = by_section.get("ec2_rds", {}).get("ec2", {})
    rds = by_section.get("ec2_rds", {}).get("rds", {})
    waste = by_section.get("ec2_rds", {}).get("waste", {})
    iam = by_section.get("iam_hygiene", {})
    ct = by_section.get("cloudtrail_risk", {})
    s3h = by_section.get("s3_hygiene", {})
    bk = by_section.get("backup_status", {})
    bk_jobs = bk.get("jobs", {})
    bk_states = bk_jobs.get("by_state", {})
    return {
        "ec2_running": ec2.get("by_state", {}).get("running", 0),
        "ec2_total": ec2.get("total", 0),
        "rds_total": rds.get("total", 0),
        "unattached_volumes": len(waste.get("unattached_volumes", [])),
        "unassociated_eips": len(waste.get("unassociated_eips", [])),
        "users_no_mfa": len(iam.get("users_console_no_mfa", [])),
        "stale_keys": len(iam.get("stale_access_keys", [])),
        "risk_events": ct.get("count", 0),
        "buckets_no_public_block": len(s3h.get("without_public_access_block", [])),
        "buckets_no_encryption": len(s3h.get("without_default_encryption", [])),
        "backup_failed": bk_states.get("FAILED", 0)
        + bk_states.get("ABORTED", 0)
        + bk_states.get("EXPIRED", 0),
        "backup_total": bk_jobs.get("total", 0),
        "backup_protected": bk.get("protected", {}).get("total", 0),
    }


def _severity(metrics, root):
    levels = []
    if root.get("access_key_1_active") or root.get("access_key_2_active"):
        levels.append(("CRITICAL", "루트 계정 액세스 키가 활성화되어 있음"))
    if not root.get("mfa_enabled"):
        levels.append(("CRITICAL", "루트 계정 MFA가 비활성 상태"))
    if metrics["risk_events"] > 0:
        levels.append(("HIGH", f"최근 24시간 위험 이벤트 {metrics['risk_events']}건"))
    if metrics["users_no_mfa"] > 0:
        levels.append(("HIGH", f"MFA 미설정 콘솔 사용자 {metrics['users_no_mfa']}명"))
    if metrics["buckets_no_public_block"] > 0:
        levels.append(("HIGH", f"퍼블릭 액세스 차단이 안 된 S3 버킷 {metrics['buckets_no_public_block']}개"))
    if metrics["stale_keys"] > 0:
        levels.append(("MEDIUM", f"장기 미사용 액세스 키 {metrics['stale_keys']}개"))
    if metrics["buckets_no_encryption"] > 0:
        levels.append(("MEDIUM", f"기본 암호화 미설정 S3 버킷 {metrics['buckets_no_encryption']}개"))
    if metrics["unattached_volumes"] > 0:
        levels.append(("LOW", f"미연결 EBS 볼륨 {metrics['unattached_volumes']}개"))
    if metrics["unassociated_eips"] > 0:
        levels.append(("LOW", f"미사용 EIP {metrics['unassociated_eips']}개"))
    if metrics["backup_failed"] > 0:
        levels.append(("HIGH", f"최근 24시간 백업 실패 {metrics['backup_failed']}건"))
    return levels


def _badge(level):
    return f'<span class="badge b-{level.lower()}">{level}</span>'


EC2_STATE_COLORS = {
    "running": "#16A34A",
    "stopped": "#9AA1AD",
    "pending": "#F59E0B",
    "stopping": "#F59E0B",
    "shutting-down": "#DC6803",
    "terminated": "#1A1A1A",
}

BACKUP_STATE_COLORS = {
    "COMPLETED": "#16A34A",
    "RUNNING": "#1A1A1A",
    "PENDING": "#9AA1AD",
    "CREATED": "#9AA1AD",
    "FAILED": "#E60012",
    "ABORTED": "#DC6803",
    "EXPIRED": "#B45309",
    "PARTIAL": "#F59E0B",
}


def _ec2_donut(by_section):
    by_state = (
        by_section.get("ec2_rds", {}).get("ec2", {}).get("by_state", {}) or {}
    )
    items = [
        (state, count, EC2_STATE_COLORS.get(state, "#9AA1AD"))
        for state, count in sorted(by_state.items(), key=lambda x: -x[1])
    ]
    return _donut("EC2 상태 분포", items)


def _backup_donut(by_section):
    bk = by_section.get("backup_status", {})
    if not bk.get("enabled", True):
        return _donut("백업 작업 결과 (24h)", [])
    by_state = bk.get("jobs", {}).get("by_state", {}) or {}
    items = [
        (state, count, BACKUP_STATE_COLORS.get(state, "#9AA1AD"))
        for state, count in sorted(by_state.items(), key=lambda x: -x[1])
    ]
    return _donut("백업 작업 결과 (24h)", items)


def _section_summary(metrics, prev, history, root, by_section):
    cards = [
        ("EC2 가동 중", metrics["ec2_running"], "ec2_running"),
        ("EC2 전체", metrics["ec2_total"], "ec2_total"),
        ("RDS 인스턴스", metrics["rds_total"], "rds_total"),
        ("위험 이벤트 (24h)", metrics["risk_events"], "risk_events"),
        ("MFA 미설정 사용자", metrics["users_no_mfa"], "users_no_mfa"),
        ("장기 미사용 키", metrics["stale_keys"], "stale_keys"),
        ("퍼블릭 차단 미설정 버킷", metrics["buckets_no_public_block"], "buckets_no_public_block"),
        ("미연결 EBS 볼륨", metrics["unattached_volumes"], "unattached_volumes"),
        ("백업 실패 (24h)", metrics["backup_failed"], "backup_failed"),
        ("보호 리소스", metrics["backup_protected"], "backup_protected"),
    ]
    cards_html = "".join(
        f'<div class="card">'
        f'<div class="card-label">{_esc(label)}</div>'
        f'<div class="card-row">'
        f'<div class="card-value">{value} {_delta_str(value, (prev or {}).get(key))}</div>'
        f'{_sparkline((history or {}).get(key), value)}'
        f'</div></div>'
        for label, value, key in cards
    )

    findings = _severity(metrics, root)
    findings_html = (
        "".join(f"<li>{_badge(lvl)} {_esc(msg)}</li>" for lvl, msg in findings)
        if findings
        else "<li>특이사항 없음</li>"
    )
    has_history = any((history or {}).values())
    trend_note = (
        '<p class="summary-note">최근 7일 추이</p>'
        if has_history
        else '<p class="summary-note">7일 추이 그래프는 데이터가 누적되면 표시됩니다.</p>'
    )
    donuts_html = f"""
    <div class="donuts">
      {_ec2_donut(by_section)}
      {_backup_donut(by_section)}
    </div>
    """
    return f"""
    <h2>요약 (Summary)</h2>
    {trend_note}
    <div class="cards">{cards_html}</div>
    {donuts_html}
    <h3>주요 발견 사항 (Findings)</h3>
    <ul class="findings">{findings_html}</ul>
    """


def _section_ec2_rds(data):
    ec2 = data.get("ec2", {})
    rds = data.get("rds", {})
    waste = data.get("waste", {})
    rows = "".join(
        f"<tr><td>{_esc(i['id'])}</td><td>{_esc(i['name'])}</td>"
        f"<td>{_esc(i['type'])}</td><td>{_esc(i['state'])}</td><td>{_esc(i['az'])}</td></tr>"
        for i in ec2.get("instances", [])
    )
    rds_rows = "".join(
        f"<tr><td>{_esc(d['id'])}</td><td>{_esc(d['engine'])}</td>"
        f"<td>{_esc(d['class'])}</td><td>{_esc(d['status'])}</td>"
        f"<td>{_esc(d['multi_az'])}</td></tr>"
        for d in rds.get("instances", [])
    )

    waste_rows = []
    for v in waste.get("unattached_volumes", []):
        waste_rows.append(
            f"<tr><td>미연결 EBS 볼륨</td><td>{_esc(v['id'])}</td>"
            f"<td>{_esc(v['type'])}</td><td class='num'>{v['size']} GB</td></tr>"
        )
    for ip in waste.get("unassociated_eips", []):
        waste_rows.append(
            f"<tr><td>미사용 EIP</td><td>{_esc(ip)}</td><td>-</td><td>-</td></tr>"
        )
    waste_html = "".join(waste_rows) or "<tr><td colspan=4>없음</td></tr>"

    top_volumes = sorted(
        waste.get("unattached_volumes", []),
        key=lambda v: v.get("size", 0),
        reverse=True,
    )[:5]
    top_bars = _bar_chart(
        "미사용 EBS 용량 TOP 5",
        [(v["id"], v["size"]) for v in top_volumes],
        value_suffix=" GB",
    )

    return f"""
    <h2>EC2 / RDS 인벤토리</h2>
    <p class="summary-note">EC2 전체 <b>{ec2.get('total', 0)}</b>대 (상태별: {_esc(ec2.get('by_state', {}))}) &middot;
       RDS 전체 <b>{rds.get('total', 0)}</b>대</p>
    <h3>EC2 인스턴스</h3>
    <table><thead><tr><th>ID</th><th>이름</th><th>타입</th><th>상태</th><th>가용영역</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=5>없음</td></tr>'}</tbody></table>
    <h3>RDS 인스턴스</h3>
    <table><thead><tr><th>ID</th><th>엔진</th><th>클래스</th><th>상태</th><th>MultiAZ</th></tr></thead>
    <tbody>{rds_rows or '<tr><td colspan=5>없음</td></tr>'}</tbody></table>
    <h3>유휴/낭비 리소스</h3>
    <p class="summary-note">미연결 EBS <b>{len(waste.get('unattached_volumes', []))}개</b>
       ({waste.get('unattached_volume_size_gb', 0)} GB) &middot;
       미사용 EIP <b>{len(waste.get('unassociated_eips', []))}개</b></p>
    {top_bars}
    <table><thead><tr><th>유형</th><th>리소스 ID / IP</th><th>상세</th><th class='num'>크기</th></tr></thead>
    <tbody>{waste_html}</tbody></table>
    """


def _section_iam(data):
    root = data.get("root", {})
    no_mfa = data.get("users_console_no_mfa", [])
    stale = data.get("stale_access_keys", [])

    root_rows = (
        f"<tr><td>MFA 활성화</td><td>{_esc(root.get('mfa_enabled'))}</td></tr>"
        f"<tr><td>액세스 키 1 활성</td><td>{_esc(root.get('access_key_1_active'))}</td></tr>"
        f"<tr><td>액세스 키 2 활성</td><td>{_esc(root.get('access_key_2_active'))}</td></tr>"
        f"<tr><td>마지막 사용 시각</td><td>{_esc(root.get('last_used'))}</td></tr>"
    )

    no_mfa_rows = "".join(f"<tr><td>{_esc(u)}</td></tr>" for u in no_mfa)

    stale_rows = "".join(
        f"<tr><td>{_esc(k['user'])}</td><td>액세스 키 #{k['key_index']}</td>"
        f"<td>{_esc(k['last_used'])}</td><td>{_esc(k['last_rotated'])}</td></tr>"
        for k in stale
    )
    return f"""
    <h2>IAM 보안 점검</h2>
    <h3>루트 계정</h3>
    <table><thead><tr><th>항목</th><th>상태</th></tr></thead>
    <tbody>{root_rows}</tbody></table>
    <h3>MFA 미설정 사용자 (콘솔 로그인 가능)</h3>
    <p class="summary-note">총 <b>{len(no_mfa)}</b>명</p>
    <table><thead><tr><th>사용자</th></tr></thead>
    <tbody>{no_mfa_rows or '<tr><td>없음</td></tr>'}</tbody></table>
    <h3>장기 미사용 액세스 키 ({data.get('stale_threshold_days', 90)}일 이상)</h3>
    <p class="summary-note">총 <b>{len(stale)}</b>건</p>
    <table><thead><tr><th>사용자</th><th>액세스 키</th><th>마지막 사용</th><th>마지막 회전</th></tr></thead>
    <tbody>{stale_rows or '<tr><td colspan=4>없음</td></tr>'}</tbody></table>
    """


def _section_cloudtrail(data):
    rows = "".join(
        f"<tr><td>{_esc(f['time'])}</td><td>{_esc(f['event_name'])}</td>"
        f"<td>{_esc(f['user'])}</td><td>{_esc(f['source'])}</td></tr>"
        for f in data.get("findings", [])
    )
    timeline = _timeline_24h(data.get("findings", []))
    return f"""
    <h2>CloudTrail 위험 이벤트 (최근 {data.get('window_hours', 24)}시간)</h2>
    <p>총 건수: <b>{data.get('count', 0)}건</b></p>
    {timeline}
    <table><thead><tr><th>시각</th><th>이벤트</th><th>사용자</th><th>서비스</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=4>없음</td></tr>'}</tbody></table>
    """


def _section_s3(data):
    no_block = data.get("without_public_access_block", [])
    no_enc = data.get("without_default_encryption", [])
    rows = []
    for b in no_block:
        rows.append(f"<tr><td>{_esc(b)}</td><td>퍼블릭 액세스 차단 미설정</td></tr>")
    for b in no_enc:
        rows.append(f"<tr><td>{_esc(b)}</td><td>기본 암호화 미설정</td></tr>")
    body = "".join(rows) or "<tr><td colspan=2>위반 사항 없음</td></tr>"
    return f"""
    <h2>S3 버킷 보안 점검</h2>
    <p class="summary-note">전체 버킷 <b>{data.get('total_buckets', 0)}</b>개 &middot;
       퍼블릭 차단 미설정 <b>{len(no_block)}</b>개 &middot;
       암호화 미설정 <b>{len(no_enc)}</b>개</p>
    <table><thead><tr><th>버킷</th><th>위반 항목</th></tr></thead>
    <tbody>{body}</tbody></table>
    """


def _section_backup(data):
    if not data.get("enabled", True):
        return f"""
        <h2>백업 상태 (AWS Backup)</h2>
        <p class="summary-note">AWS Backup 사용 권한 없음 또는 미활성 ({_esc(data.get('error'))})</p>
        """
    jobs = data.get("jobs", {})
    protected = data.get("protected", {})
    by_state = jobs.get("by_state", {}) or {}
    by_type = jobs.get("by_resource_type", {}) or {}
    protected_by_type = protected.get("by_type", {}) or {}

    failed_rows = "".join(
        f"<tr><td>{_esc((j.get('completed') or j.get('created') or '')[:19])}</td>"
        f"<td>{_esc(j.get('resource_type'))}</td>"
        f"<td>{_esc((j.get('resource_arn') or '').split(':')[-1])}</td>"
        f"<td>{_esc(j.get('vault'))}</td>"
        f"<td>{_esc(j.get('state'))}</td>"
        f"<td>{_esc(j.get('status_message'))}</td></tr>"
        for j in jobs.get("failed", [])
    )

    state_rows = "".join(
        f"<tr><td>{_esc(state)}</td><td class='num'>{count}</td></tr>"
        for state, count in sorted(by_state.items(), key=lambda x: -x[1])
    )

    type_rows = "".join(
        f"<tr><td>{_esc(t)}</td><td class='num'>{count}</td></tr>"
        for t, count in sorted(protected_by_type.items(), key=lambda x: -x[1])
    )

    protected_palette = [
        "#1A1A1A", "#E60012", "#F59E0B", "#16A34A",
        "#9AA1AD", "#6B7280", "#B45309", "#0F4FB3",
    ]
    protected_items = [
        (t, count, protected_palette[i % len(protected_palette)])
        for i, (t, count) in enumerate(
            sorted(protected_by_type.items(), key=lambda x: -x[1])
        )
    ]
    protected_donut = _donut("보호 리소스 종류 분포", protected_items)

    return f"""
    <h2>백업 상태 (AWS Backup, 최근 {data.get('window_hours', 24)}시간)</h2>
    <p class="summary-note">백업 작업 총 <b>{jobs.get('total', 0)}</b>건 &middot;
       보호 리소스 <b>{protected.get('total', 0)}</b>개 &middot;
       리소스 종류 {_esc(by_type) if by_type else '-'}</p>
    <h3>작업 상태별 카운트</h3>
    <table><thead><tr><th>상태</th><th class='num'>건수</th></tr></thead>
    <tbody>{state_rows or '<tr><td colspan=2>없음</td></tr>'}</tbody></table>
    <h3>실패/중단 작업</h3>
    <table><thead><tr><th>완료/생성</th><th>리소스 타입</th><th>리소스</th><th>볼트</th><th>상태</th><th>메시지</th></tr></thead>
    <tbody>{failed_rows or '<tr><td colspan=6>없음</td></tr>'}</tbody></table>
    <h3>보호 리소스 종류</h3>
    <div class="donuts donuts-1">{protected_donut}</div>
    <table><thead><tr><th>리소스 타입</th><th class='num'>개수</th></tr></thead>
    <tbody>{type_rows or '<tr><td colspan=2>보호 리소스 없음</td></tr>'}</tbody></table>
    """


SECTION_RENDERERS = {
    "ec2_rds": _section_ec2_rds,
    "iam_hygiene": _section_iam,
    "cloudtrail_risk": _section_cloudtrail,
    "s3_hygiene": _section_s3,
    "backup_status": _section_backup,
}


def _css():
    return f"""
    :root {{
      --brand:      {BRAND};
      --brand-dark: #000000;
      --brand-50:   #F7F7F8;
      --brand-100:  #ECECEE;
      --brand-200:  #D9D9DD;
      --accent:     #E60012;
      --ink:        #1A1A1A;
      --muted:      #6B7280;
      --line:       #E2E2E6;
      --bg:         #F8F8F9;
    }}
    body {{ font-family:-apple-system,Segoe UI,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;
           max-width:1100px; margin:0 auto; color:var(--ink); background:var(--bg); }}
    .header {{ background:#fff; color:var(--ink); padding:20px 28px;
              display:flex; align-items:center; justify-content:space-between;
              border:1px solid var(--line); border-radius:6px;
              margin:24px 28px 0; }}
    .header .brand {{ display:flex; align-items:center; gap:14px; }}
    .header .logo {{ height:40px; width:auto; }}
    .header .msp {{ font-size:12px; color:var(--muted); letter-spacing:.5px;
                   text-transform:uppercase; font-weight:600; }}
    .header h1 {{ margin:4px 0 0; font-size:22px; color:var(--ink); }}
    .header .meta {{ text-align:right; font-size:13px; color:var(--muted); }}
    .header .meta b {{ color:var(--ink); }}
    .container {{ padding:24px 28px; }}
    h2 {{ margin-top:32px; color:var(--ink);
          border-bottom:2px solid var(--ink); padding-bottom:6px; }}
    h3 {{ margin-top:20px; color:var(--ink); font-size:15px; }}
    table {{ border-collapse:separate; border-spacing:0; width:100%; margin:8px 0 16px;
             font-size:13px; background:#fff; border:1px solid var(--line);
             border-radius:6px; overflow:hidden; }}
    th,td {{ border-bottom:1px solid var(--line); padding:8px 12px; text-align:left;
             vertical-align:top; }}
    th {{ background:var(--brand-100); color:var(--ink); font-weight:600;
          font-size:12px; text-transform:uppercase; letter-spacing:.3px; }}
    tr:last-child td {{ border-bottom:0; }}
    tbody tr:hover {{ background:var(--brand-50); }}
    td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:8px 0 16px; }}
    .card {{ background:#fff; border:1px solid var(--line); border-radius:6px;
             padding:12px 14px; }}
    .card-label {{ font-size:12px; color:var(--muted); text-transform:uppercase;
                   letter-spacing:.3px; font-weight:600; }}
    .card-row {{ display:flex; align-items:flex-end; justify-content:space-between;
                gap:8px; margin-top:4px; }}
    .card-value {{ font-size:24px; font-weight:700; color:var(--ink);
                   font-variant-numeric:tabular-nums; line-height:1.1; }}
    .spark {{ width:80px; height:24px; color:var(--muted); flex-shrink:0; }}
    .donuts {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px;
              margin:8px 0 16px; }}
    .donut-card {{ background:#fff; border:1px solid var(--line); border-radius:6px;
                  padding:14px 16px; }}
    .donut-title {{ font-size:12px; color:var(--muted); text-transform:uppercase;
                   letter-spacing:.3px; font-weight:600; margin-bottom:10px; }}
    .donut-body {{ display:flex; align-items:center; gap:18px; }}
    .donut {{ width:120px; height:120px; flex-shrink:0; }}
    .legend {{ list-style:none; padding:0; margin:0; flex:1; font-size:13px; }}
    .legend li {{ display:flex; align-items:center; gap:8px; padding:3px 0; }}
    .legend-swatch {{ width:10px; height:10px; border-radius:2px; flex-shrink:0; }}
    .legend-label {{ flex:1; color:var(--ink); }}
    .legend-value {{ color:var(--muted); font-variant-numeric:tabular-nums; }}
    .donuts-1 {{ grid-template-columns:1fr; }}
    .bar-chart {{ background:#fff; border:1px solid var(--line); border-radius:6px;
                 padding:14px 16px; margin:8px 0 16px; }}
    .bar-title {{ font-size:12px; color:var(--muted); text-transform:uppercase;
                 letter-spacing:.3px; font-weight:600; margin-bottom:10px; }}
    .bars {{ list-style:none; padding:0; margin:0; }}
    .bars li {{ display:grid; grid-template-columns:160px 1fr 80px;
                align-items:center; gap:10px; padding:4px 0; font-size:13px; }}
    .bar-label {{ color:var(--ink); white-space:nowrap; overflow:hidden;
                 text-overflow:ellipsis; }}
    .bar-track {{ background:var(--brand-100); height:14px; border-radius:3px;
                 position:relative; }}
    .bar-fill {{ background:var(--ink); height:100%; border-radius:3px;
                display:block; }}
    .bar-value {{ color:var(--muted); text-align:right;
                 font-variant-numeric:tabular-nums; }}
    .timeline {{ background:#fff; border:1px solid var(--line); border-radius:6px;
                padding:14px 16px; margin:8px 0 16px; }}
    .timeline-title {{ font-size:12px; color:var(--muted); text-transform:uppercase;
                      letter-spacing:.3px; font-weight:600; margin-bottom:6px; }}
    .timeline svg {{ width:100%; height:auto; }}
    .d-up {{ color:#B42318; font-size:13px; margin-left:6px; font-weight:500; }}
    .d-down {{ color:#067647; font-size:13px; margin-left:6px; font-weight:500; }}
    .d-zero {{ color:var(--muted); font-size:13px; margin-left:6px; }}
    .findings {{ background:#fff; border:1px solid var(--line); border-radius:6px;
                 list-style:none; padding:0; margin:8px 0 16px; overflow:hidden; }}
    .findings li {{ padding:9px 14px; border-bottom:1px solid var(--line); }}
    .findings li:last-child {{ border-bottom:0; }}
    p.summary-note {{ color:var(--muted); font-size:13px; margin:6px 2px; }}
    .badge {{ display:inline-block; padding:2px 8px; border-radius:4px;
              font-size:11px; font-weight:600; margin-right:8px; color:#fff; }}
    .b-critical {{ background:var(--accent); }}
    .b-high     {{ background:#DC6803; }}
    .b-medium   {{ background:#B45309; }}
    .b-low      {{ background:#6B7280; }}
    p, ul, li {{ color:var(--ink); }}
    .footer {{ font-size:12px; color:var(--muted); padding:16px 28px;
               border-top:1px solid var(--line); background:#fff; }}
    """


def handler(event, context):
    sections = event.get("sections") or []
    by_section = {s.get("section"): s for s in sections if isinstance(s, dict)}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    metrics = _compute_metrics(by_section)
    prev = _load_prev_metrics()
    history = _load_history_metrics(days=7)
    root = by_section.get("iam_hygiene", {}).get("root", {})

    body_parts = [_section_summary(metrics, prev, history, root, by_section)]
    for s in sections:
        if not isinstance(s, dict):
            continue
        renderer = SECTION_RENDERERS.get(s.get("section"))
        if renderer:
            body_parts.append(renderer(s))
        else:
            body_parts.append(f"<pre>{html.escape(json.dumps(s, indent=2, default=str))}</pre>")

    customer_label = f" &middot; 고객사: <b>{_esc(CUSTOMER)}</b>" if CUSTOMER else ""
    html_doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{_esc(MSP_NAME)} AWS 일일 보고서 {today}</title>
<style>{_css()}</style></head><body>
<div class="header">
  <div class="brand">
    {f'<img class="logo" src="{_esc(LOGO_URL)}" alt="{_esc(MSP_NAME)}"/>' if LOGO_URL else ''}
    <div>
      <div class="msp">{_esc(MSP_NAME)}</div>
      <h1>AWS 일일 보고서</h1>
    </div>
  </div>
  <div class="meta">
    <div>보고일자: {today}</div>
    <div>계정: <b>{_esc(ACCOUNT)}</b>{customer_label}</div>
    <div>환경: <b>{_esc(ENV)}</b></div>
  </div>
</div>
<div class="container">
{''.join(body_parts)}
</div>
<div class="footer">{_esc(MSP_NAME)} AWS 일일 보고서 &middot; 본 보고서의 공유 URL은 설정된 만료 기간(기본 7일) 후 사용 불가 합니다.</div>
</body></html>"""

    payload = {
        "metadata": {
            "date": today,
            "account": ACCOUNT,
            "env": ENV,
            "msp": MSP_NAME,
            "customer": CUSTOMER,
        },
        "metrics": metrics,
        "sections": sections,
    }

    return {
        "html": html_doc,
        "json": json.dumps(payload, default=str),
        "date": today,
    }
