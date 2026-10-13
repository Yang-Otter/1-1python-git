"""Gemini API 호출 모듈 (REST, POST 방식)

- recommend_city : 날짜 → 1차 추천 JSON
- generate_report: 1차 추천 + 맛집/관광지 → Markdown 리포트
"""

import json
import re

import requests

DEFAULT_MODEL = "gemini-3.5-flash-lite"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 1차 추천 JSON 필수 키와 타입
REQUIRED_KEYS = {
    "recommended_city": str,
    "weather": str,
    "events": list,
    "reason": str,
}


class LLMError(Exception):
    """LLM 호출 실패 (인증/쿼터/네트워크/응답 형식)."""

    def __init__(self, err_type: str, message: str):
        super().__init__(message)
        self.err_type = err_type
        self.message = message


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------
def build_recommend_prompt(travel_date: str) -> str:
    return f"""너는 국내 여행 추천 도우미다.
여행 날짜: {travel_date}

이 날짜(계절/시기)에 대한민국 국내에서 여행하기 좋은 도시 1곳을 추천하라.
설명, 마크다운, 코드블록 없이 아래 형식의 JSON 객체 하나만 출력한다.

{{
  "recommended_city": "도시 이름. 지도 검색에 쓸 수 있도록 시/군 이름만 (예: 제주, 강릉, 경주)",
  "weather": "해당 시기의 일반적인 날씨 요약 1문장",
  "events": ["해당 시기 행사/축제 후보 1~3개"],
  "reason": "추천 근거 2~4문장"
}}"""


def build_retry_prompt(travel_date: str) -> str:
    return f"""이전 응답을 JSON으로 파싱하지 못했다.
여행 날짜 {travel_date}에 국내에서 여행하기 좋은 도시 1곳을 추천하되,
다른 텍스트 없이 아래 4개 필수 키만 가진 JSON 객체 하나만 출력하라.

- recommended_city: string (시/군 이름만)
- weather: string
- events: array of string (1~3개)
- reason: string (2~4문장)"""


def build_report_prompt(travel_date: str, rec: dict,
                        restaurants: list, attractions: list) -> str:
    payload = {
        "recommendation": rec,
        "restaurants": restaurants,
        "attractions": attractions,
    }
    return f"""아래 데이터만 사용해 국내 여행 리포트를 Markdown으로 작성하라.

규칙:
- 아래 제목 구조를 이 순서 그대로 사용하고, 다른 섹션은 추가하지 않는다.
- 맛집/관광지는 제공된 목록에 있는 장소만 쓴다. 목록이 비어 있으면 그 섹션에 "- 데이터 없음"이라고만 쓴다.
- 장소에 url이 있으면 [장소명](url) 형태의 링크로 쓰고, 주소와 분류를 함께 적는다.
- 1일 일정은 오전/오후/저녁으로 나누고, 가능하면 제공된 맛집·관광지 중에서 고른다.
  목록이 비어 있으면 특정 상호명 없이 일반적인 활동으로 제안한다.
- 오류 요약 섹션은 쓰지 않는다(프로그램이 따로 추가한다).
- 코드블록으로 감싸지 말고 Markdown 본문만 출력한다.

제목 구조:
# {travel_date} 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 맛집 추천
## 관광지 추천
## 1일 일정 제안

데이터(JSON):
{json.dumps(payload, ensure_ascii=False, indent=2)}"""


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------
def strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_recommendation(text: str) -> dict:
    """1차 추천 텍스트를 JSON으로 파싱하고 필수 키/타입을 검증한다."""
    try:
        data = json.loads(strip_code_fence(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 디코딩 실패({e.msg})")

    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아님")

    for key, expected_type in REQUIRED_KEYS.items():
        if key not in data:
            raise ValueError(f"필수 키 누락: {key}")
        if not isinstance(data[key], expected_type):
            raise ValueError(f"타입 오류: {key}는 {expected_type.__name__}이어야 함")

    city = data["recommended_city"].strip()
    events = [str(e).strip() for e in data["events"] if str(e).strip()][:3]
    if not city:
        raise ValueError("recommended_city가 비어 있음")
    if not events:
        raise ValueError("events가 비어 있음")

    return {
        "recommended_city": city,
        "weather": data["weather"].strip(),
        "events": events,
        "reason": data["reason"].strip(),
    }


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------
class GeminiClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: int = 60):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _generate(self, prompt: str, json_mode: bool = False) -> str:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if json_mode:
            # JSON 형태로만 응답하도록 요청
            body["generationConfig"] = {"responseMimeType": "application/json"}

        try:
            resp = requests.post(
                GEMINI_URL.format(model=self.model),
                headers={
                    "x-goog-api-key": self.api_key,  # 키는 URL이 아닌 헤더로 전달
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self.timeout,
            )
        except requests.Timeout:
            raise LLMError("NETWORK_ERROR", "LLM 요청 시간 초과")
        except requests.RequestException as e:
            raise LLMError("NETWORK_ERROR", f"LLM 네트워크 오류({type(e).__name__})")

        status = resp.status_code
        if status in (401, 403) or (status == 400 and "API_KEY_INVALID" in resp.text):
            raise LLMError("AUTH_ERROR", f"LLM 인증 실패(HTTP {status}). GEMINI_API_KEY를 확인하세요.")
        if status == 429:
            raise LLMError("QUOTA_ERROR", "LLM 호출 한도 초과(HTTP 429)")
        if status == 404:
            raise LLMError("HTTP_ERROR", f"모델을 찾을 수 없음(HTTP 404): {self.model}")
        if not resp.ok:
            raise LLMError("HTTP_ERROR", f"LLM 요청 실패(HTTP {status})")

        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("RESPONSE_ERROR", "LLM 응답에서 텍스트를 찾을 수 없음")

    def recommend_city(self, travel_date: str, errors: list) -> dict | None:
        """파싱 실패 시 프롬프트를 바꿔 최대 1회만 재시도한다."""
        prompts = [build_recommend_prompt(travel_date), build_retry_prompt(travel_date)]
        for attempt, prompt in enumerate(prompts, start=1):
            text = self._generate(prompt, json_mode=True)
            try:
                return parse_recommendation(text)
            except ValueError as e:
                errors.append({
                    "step": "recommendation",
                    "type": "PARSE_ERROR",
                    "message": f"{attempt}차 시도 파싱 실패: {e}",
                })
                if attempt < len(prompts):
                    print(" - JSON 파싱 실패, 필수 키만 다시 요청합니다(1회).")
        return None

    def generate_report(self, travel_date: str, rec: dict,
                        restaurants: list, attractions: list) -> str:
        prompt = build_report_prompt(travel_date, rec, restaurants, attractions)
        text = strip_code_fence(self._generate(prompt))
        if not text:
            raise LLMError("RESPONSE_ERROR", "LLM이 빈 리포트를 반환함")
        return text
