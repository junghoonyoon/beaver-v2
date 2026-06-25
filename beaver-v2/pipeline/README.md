# 비버 종목 검색 파이프라인

현재 `pipeline/`은 종목 검색 앱 전용 백엔드입니다.

## 흐름

```text
유튜브 채널 목록
→ 최근 영상 메타데이터 수집
→ 자막 캐시 저장
→ KRX·미국 상장종목정보 캐시 기반 종목명/법인명/초성/코드/ISIN/티커 자동완성
→ 검색 종목을 언급한 영상 선별
→ 로컬 Ollama(qwen3:14b)로 유튜버 의견 분석
→ 브라우저에 완료된 카드부터 순차 표시
```

## 주요 파일

| 파일 | 역할 |
|---|---|
| `sync_search_index.py` | 최근 영상 자막 검색 인덱스 생성 |
| `sync_krx_listed.py` | KRX 상장종목정보 즉시 갱신 |
| `sync_us_listed.py` | 미국 상장종목정보 즉시 갱신 |
| `search_server.py` | 로컬 웹 서버/API |
| `stock_search.py` | 종목 자동완성, 검색, 분석 캐시 |
| `krx_listed.py` | 공공데이터포털 KRX 상장종목정보 수집/캐시 |
| `us_listed.py` | Nasdaq Trader 미국 상장종목정보 수집/캐시 |
| `youtube.py` | YouTube 영상/자막 수집 |
| `analyze.py` | Ollama/Gemini 분석 |
| `config.py` | 채널 목록과 설정 |
| `runtime_settings.py` | `설정.txt` 값 로드 |

## 캐시

- `cache/search_index.json`: 검색 인덱스
- `cache/krx_listed_stocks.json`: KRX 상장종목정보 캐시
- `cache/us_listed_stocks.json`: 미국 상장종목정보 캐시
- `cache/transcripts/`: 영상별 자막 캐시
- `cache/stock_analysis/`: 종목별 유튜버 의견 분석 캐시

`설정.txt`에 `공공데이터키`가 있으면 서버 시작 시 KRX 상장종목정보를 하루 1회
백그라운드로 갱신합니다. 즉시 갱신하려면:

```text
./.venv/bin/python sync_krx_listed.py
```

미국 상장종목은 별도 키 없이 Nasdaq Trader 공개 파일을 하루 1회 갱신합니다.

```text
./.venv/bin/python sync_us_listed.py
```

## 실행

루트 폴더의 `종목검색실행.command`를 사용하세요.

```text
../종목검색실행.command
```
