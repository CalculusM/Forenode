#!/usr/bin/env bash
# ------------------------------------------------------------------
# Forenode 업데이트 스크립트 (Docker 경로, 2026-09-28 작성)
#
# 순서: 현재 이미지 보존(prev·커밋 태그) / git pull / 재빌드 / 재기동 / 헬스체크 / 스모크 시험
#       헬스체크 또는 스모크 시험 실패 시 직전 이미지로 자동 복귀
# 사용: cd /srv/forenode/app/deploy && ./update.sh
#       (최초 1회 chmod +x update.sh)
# 비고: 소스 폴더는 자동으로 되돌리지 않음(원인 확인용). 복귀 후 안내 메시지 참조
# ------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(cd .. && pwd)"
IMAGE="forenode-app"
HEALTH_URL="http://127.0.0.1:8501/_stcore/health"

log() { printf '[update %s] %s\n' "$(date '+%F %T')" "$*"; }

wait_health() {
  local i
  for i in $(seq 1 60); do
    if [ "$(curl -fsS -m 3 "$HEALTH_URL" 2>/dev/null || true)" = "ok" ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback() {
  log "실패 감지: 직전 이미지(${IMAGE}:prev)로 복귀"
  if docker image inspect "${IMAGE}:prev" >/dev/null 2>&1; then
    docker tag "${IMAGE}:prev" "${IMAGE}:latest"
    docker compose up -d --no-build
    if wait_health; then
      log "복귀 완료(헬스체크 ok). 소스는 ${NEW_SHA} 상태 유지"
      log "원인 수정 전 재빌드 금지. 소스까지 되돌리려면: git -C \"$REPO_DIR\" checkout ${PREV_SHA}"
    else
      log "복귀 후에도 헬스체크 실패: docker compose logs --tail 200 app 확인 필요"
    fi
  else
    log "직전 이미지 없음(최초 배포). docker compose logs --tail 200 app 확인 필요"
  fi
  exit 1
}

PREV_SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
NEW_SHA="$PREV_SHA"

if docker image inspect "${IMAGE}:latest" >/dev/null 2>&1; then
  docker tag "${IMAGE}:latest" "${IMAGE}:prev"
  docker tag "${IMAGE}:latest" "${IMAGE}:${PREV_SHA}"
  log "현재 이미지 보존: ${IMAGE}:prev, ${IMAGE}:${PREV_SHA}"
fi

log "git pull (fast-forward 전용)"
git -C "$REPO_DIR" pull --ff-only
NEW_SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
log "소스 ${PREV_SHA} 에서 ${NEW_SHA} 로 갱신"

log "이미지 빌드"
docker compose build || rollback

log "컨테이너 재기동"
docker compose up -d || rollback

log "헬스체크 대기(최대 120초)"
wait_health || rollback

log "스모크 시험(app.py·pages/* 전 페이지 1회 실행)"
docker compose exec -T app python deploy/smoke_test.py || rollback

docker tag "${IMAGE}:latest" "${IMAGE}:${NEW_SHA}"
log "업데이트 완료: ${IMAGE}:${NEW_SHA}"
