# 국내 여행지 추천 프로그램 (Gemini + Kakao Local)

여행 날짜를 입력하면 Gemini가 그 시기에 가기 좋은 국내 도시를 추천하고, Kakao Local API로 해당 도시의 맛집과 관광지를 검색한 뒤, 두 결과를 합쳐 Markdown 여행 리포트를 만드는 CLI 프로그램입니다.

## 동작 흐름

```
-date 입력
  → [1/4] Gemini: 1차 추천 JSON (recommended_city, weather, events, reason)
  → [2/4] Kakao Local: "{도시} 맛집" 검색 (카테고리 FD6 음식점)
  → [3/4] Kakao Local: "{도시} 관광명소" 검색 (카테고리 AT4 관광명소)
  → [4/4] Gemini: 추천 + 장소 목록으로 최종 리포트(Markdown) 생성
  → results/ 에 원본 JSON과 리포트 저장
```

Gemini는 `POST`(요청 본문에 프롬프트를 담아 생성 요청), Kakao Local은 `GET`(쿼리 파라미터로 조회 요청) 방식으로 호출합니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `travel_planner.py` | 실행 진입점. 입력 검증, 전체 흐름, 오류 목록 관리, 결과 저장 |
| `llm_client.py` | Gemini 호출, 1차 추천 JSON 파싱/검증, 리포트 생성 |
| `place_client.py` | Kakao Local 키워드 검색, 응답 필드 정리 |
| `.env.example` | 필요한 환경변수 이름 샘플 (실제 키 없음) |

## 설치

Python 3.10 이상이 필요합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## API 키 설정

### 1. 키 발급

**Gemini**: [Google AI Studio](https://aistudio.google.com/apikey)에서 API 키를 발급합니다.

**Kakao Local**: [Kakao Developers](https://developers.kakao.com)에서 애플리케이션을 만들고 `앱 키 > REST API 키`를 사용합니다. 앱 설정에서 **카카오맵 사용 설정**이 꺼져 있으면 403 오류가 발생하니 함께 확인합니다.

### 2. .env 파일 작성

```bash
cp .env.example .env
```

`.env` 파일을 열어 키를 입력합니다.

```
GEMINI_API_KEY=발급받은_키
KAKAO_REST_API_KEY=발급받은_키
```

`.env` 대신 환경변수로 설정해도 됩니다(현재 터미널 세션에만 적용).

```bash
# macOS / Linux
export GEMINI_API_KEY="YOUR_KEY"
export KAKAO_REST_API_KEY="YOUR_KEY"
```

```powershell
# Windows PowerShell
$env:GEMINI_API_KEY="YOUR_KEY"
$env:KAKAO_REST_API_KEY="YOUR_KEY"
```

사용할 Gemini 모델을 바꾸려면 `.env`에 `GEMINI_MODEL=모델이름`을 추가합니다(기본값 `gemini-2.5-flash`).

## 실행 방법

```bash
python travel_planner.py -date "2026-03-15"
```

`--date`로 써도 동일하게 동작합니다. 날짜 형식이 `YYYY-MM-DD`가 아니면 사용법을 출력하고 종료합니다.

실행 예시:

```
[1/4] 1차 추천 생성 중(LLM)...
 - recommended_city: "제주"
[2/4] 맛집 검색 중(Kakao Local)...
 - 맛집 5곳 검색 완료
[3/4] 관광지 검색 중(Kakao Local)...
 - 관광지 5곳 검색 완료
[4/4] 최종 리포트 생성 중(LLM)...
 - 리포트 생성 완료
완료! results/2026-03-15_travel_plan.md 를 확인하세요.
     원본 데이터: results/2026-03-15_raw.json
```

## 결과물 확인

실행하면 `results/` 폴더에 입력한 여행 날짜 기준으로 두 파일이 생성됩니다. 같은 날짜로 다시 실행하면 덮어씁니다.

**`YYYY-MM-DD_raw.json`** (원본 데이터): 1차 추천 JSON(`recommendation`), 맛집 검색 결과(`restaurants`), 관광지 검색 결과(`attractions`), 오류 요약(`errors`)이 들어 있습니다. 장소 검색 결과가 0건이면 빈 배열, 오류가 없으면 `errors`도 빈 배열입니다.

**`YYYY-MM-DD_travel_plan.md`** (최종 리포트): 추천 지역, 추천 이유, 날씨 요약, 행사/축제, 맛집 추천, 관광지 추천, 1일 일정 제안(오전/오후/저녁), 오류 요약으로 구성됩니다.

## 오류 처리

| 상황 | 처리 | errors 기록 |
|---|---|---|
| API 키 미설정 | 설정 방법 안내 후 즉시 종료 | - |
| 1차 추천 JSON 파싱 실패 | 필수 키만 다시 요청하는 프롬프트로 **1회만** 재시도, 또 실패하면 종료 | `PARSE_ERROR` |
| 장소 검색 인증 실패(401/403) | 해당 섹션 "데이터 없음" 처리 후 계속 진행 | `AUTH_ERROR` |
| 장소 검색 호출 한도 초과(429) | 위와 동일 | `QUOTA_ERROR` |
| 네트워크 오류/시간 초과 | 위와 동일 | `NETWORK_ERROR` |
| 장소 검색 결과 0건 | 위와 동일 (키워드를 바꿔 재검색하지 않음) | `EMPTY_RESULT` |
| 최종 리포트 LLM 실패 | 기본 템플릿으로 리포트 작성 후 저장 | `AUTH_ERROR` 등 |

맛집과 관광지 검색은 서로 독립적으로 처리되어, 한쪽이 실패해도 다른 쪽 결과는 리포트에 포함됩니다. 모든 요청에는 타임아웃이 설정되어 있습니다.

자세한 메시지는 [ERROR_MESSAGES.md](ERROR_MESSAGES.md) 참고

## API 키 보안 주의 사항

API 키는 코드, README, 실행 로그, 결과 파일 어디에도 직접 쓰지 않고 `.env` 또는 환경변수로만 관리합니다. 키를 코드에 넣으면 저장소를 공유하거나 GitHub에 올리는 순간 그대로 공개되고, 과금이 걸린 API라면 타인이 내 키로 호출해 비용이 발생할 수 있습니다. 환경변수로 분리해 두면 키를 교체할 때 코드를 고칠 필요도 없습니다.

`.env`는 `.gitignore`에 포함되어 커밋되지 않습니다. 이미 실수로 커밋했다면 아래처럼 추적을 해제하고, **해당 키는 유출된 것으로 보고 즉시 재발급**합니다.

```bash
git rm --cached .env
git commit -m "Remove .env from tracking"
```

프로그램은 API 키를 URL이 아닌 요청 헤더로만 보내며, 오류 메시지와 `errors` 기록에도 키나 요청 헤더를 남기지 않습니다.
