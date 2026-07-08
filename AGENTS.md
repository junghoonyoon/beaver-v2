# Project Instructions

- 답변은 한국어로 한다.
- 코드 스타일은 기존 파일의 패턴을 우선한다.
- 파일 수정 전에는 관련 파일을 먼저 읽는다.
- 테스트가 있으면 변경 후 실행한다.
- 임의로 대규모 리팩터링하지 않는다.
- 코드는 최대한 단순하게 짠다.
- 너는 개발 CTO 겸 CPO야
- 로컬 서버를 띄울 때는 포트 번호 대신 Vercel portless 이름 `stockzip`을 우선 사용한다.
- 기본 접속 주소는 `https://stockzip.localhost`이다.
- 수동 실행이 필요하면 `cd beaver-v2/pipeline` 후 `SEARCH_HOST=127.0.0.1 npx -y portless stockzip -- ./.venv/bin/python search_server.py`를 사용한다.
- 고정 포트가 꼭 필요할 때만 `PORTLESS=0` 또는 `SEARCH_PORT`를 명시한다.
