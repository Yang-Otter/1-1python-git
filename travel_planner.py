"""API 활용 국내 여행지 추천 프로그램 (Gemini + Kakao Local)

실행 예:
    python travel_planner.py -date "2026-03-15"
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from llm_client import DEFAULT_MODEL, GeminiClient, LLMError
from place_client import (
    ATTRACTION_CATEGORY,
    RESTAURANT_CATEGORY,
    KakaoLocalClient,
    PlaceSearchError,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"
PLACE_LIMIT = 5
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 필요한 환경변수와 발급 안내 (키 값 자체는 절대 코드에 쓰지 않는다)
REQUIRED_ENV = {
    "GEMINI_API_KEY": "Google AI Studio(https://aistudio.google.com/apikey)에서 발급",
    "KAKAO_REST_API_KEY": "Kakao Developers > 내 애플리케이션 > 앱 키 > REST API 키",
}


# ---------------------------------------------------------------------------
# 입력 / 설정
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="여행 날짜를 입력하면 국내 여행지·맛집·관광지를 추천하는 리포트를 만듭니다.",
    )
    parser.add_argument(
        "-date", "--date",
        required=True,
        help='여행 날짜 (형식: "YYYY-MM-DD", 예: "2026-03-15")',
    )
    args = parser.parse_args()

    valid = bool(DATE_PATTERN.match(args.date))
    if valid:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            valid = False
    if not valid:
        # 사용법(usage) 출력 후 종료 코드 2로 종료
        parser.error(f'날짜 형식이 올바르지 않습니다: "{args.date}" (예: -date "2026-03-15")')
    return args


def load_api_keys() -> dict:
    load_dotenv()  # .env 파일이 있으면 환경변수로 불러온다
    keys = {name: os.getenv(name, "").strip() for name in REQUIRED_ENV}
    missing = [name for name, value in keys.items() if not value]

    if missing:
        print(f"[오류] API 키가 설정되지 않았습니다: {', '.join(missing)}")
        print()
        print("설정 방법")
        print("  1) .env.example 을 복사해 .env 파일을 만듭니다.")
        print("       cp .env.example .env")
        print("  2) .env 파일에 발급받은 키를 입력합니다.")
        for name in missing:
            print(f"       {name}=발급받은_키    # {REQUIRED_ENV[name]}")
        print('  (또는 터미널에서 export 이름="키" 로 환경변수를 설정해도 됩니다.)')
        sys.exit(1)
    return keys


# ---------------------------------------------------------------------------
# 오류 관리
# ---------------------------------------------------------------------------
def add_error(errors: list, step: str, err_type: str, message: str) -> None:
    errors.append({"step": step, "type": err_type, "message": message})


# ---------------------------------------------------------------------------
# 장소 검색 (실패해도 프로그램은 계속 진행)
# ---------------------------------------------------------------------------
def search_places(kakao: KakaoLocalClient, city: str, label: str, keyword: str,
                  category_code: str, step: str, errors: list) -> list:
    query = f"{city} {keyword}"
    try:
        places = kakao.search(query, category_code=category_code, size=PLACE_LIMIT)
    except PlaceSearchError as e:
        print(f" - 오류: {e.message}")
        print(f" - {label} 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
        add_error(errors, step, e.err_type, e.message)
        return []

    if not places:
        print(" - 검색 결과 0건 (재시도하지 않고 다음 단계로 진행)")
        add_error(errors, step, "EMPTY_RESULT", f"0 results for query={query}")
        return []

    print(f" - {label} {len(places)}곳 검색 완료")
    return places


# ---------------------------------------------------------------------------
# 리포트 보조 함수
# ---------------------------------------------------------------------------
def format_errors_section(errors: list) -> str:
    lines = ["## 오류 요약(errors)"]
    if not errors:
        lines.append("- 없음")
    for e in errors:
        lines.append(f"- [{e['step']}] {e['type']}: {e['message']}")
    return "\n".join(lines)


def format_places(places: list) -> str:
    if not places:
        return "- 데이터 없음"
    lines = []
    for p in places:
        name = f"[{p['name']}]({p['url']})" if p.get("url") else p["name"]
        category = p.get("category") or "분류 없음"
        lines.append(f"- {name} ({category}) — {p['address']}")
    return "\n".join(lines)


def build_fallback_report(travel_date: str, rec: dict,
                          restaurants: list, attractions: list) -> str:
    """LLM 리포트 생성이 실패했을 때 사용하는 기본 템플릿 리포트."""
    events = "\n".join(f"- {e}" for e in rec["events"]) or "- 데이터 없음"
    return (
        f"# {travel_date} 국내 여행 추천 리포트\n\n"
        f"## 추천 지역\n{rec['recommended_city']}\n\n"
        f"## 추천 이유\n{rec['reason']}\n\n"
        f"## 날씨 요약\n{rec['weather']}\n\n"
        f"## 행사/축제\n{events}\n\n"
        f"## 맛집 추천\n{format_places(restaurants)}\n\n"
        f"## 관광지 추천\n{format_places(attractions)}\n\n"
        "## 1일 일정 제안\n"
        "- LLM 리포트 생성에 실패해 일정 제안을 만들지 못했습니다.\n"
    )


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 메인 흐름
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    keys = load_api_keys()
    travel_date = args.date

    gemini = GeminiClient(keys["GEMINI_API_KEY"], model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    kakao = KakaoLocalClient(keys["KAKAO_REST_API_KEY"])

    RESULTS_DIR.mkdir(exist_ok=True)
    raw_path = RESULTS_DIR / f"{travel_date}_raw.json"
    report_path = RESULTS_DIR / f"{travel_date}_travel_plan.md"

    errors: list = []
    raw = {
        "input_date": travel_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recommendation": None,
        "restaurants": [],
        "attractions": [],
        "errors": errors,
    }

    # [1/4] LLM 1차 추천 (JSON)
    print("[1/4] 1차 추천 생성 중(LLM)...")
    rec = None
    try:
        rec = gemini.recommend_city(travel_date, errors)
    except LLMError as e:
        print(f" - 오류: {e.message}")
        add_error(errors, "recommendation", e.err_type, e.message)

    if rec is None:
        save_json(raw_path, raw)
        print("1차 추천을 만들지 못해 종료합니다.")
        print(f"오류 내역은 {os.path.relpath(raw_path)} 에서 확인할 수 있습니다.")
        sys.exit(1)

    raw["recommendation"] = rec
    city = rec["recommended_city"]
    print(f' - recommended_city: "{city}"')

    # [2/4] 맛집 검색
    print("[2/4] 맛집 검색 중(Kakao Local)...")
    raw["restaurants"] = search_places(
        kakao, city, "맛집", "맛집", RESTAURANT_CATEGORY, "restaurant_search", errors)

    # [3/4] 관광지 검색
    print("[3/4] 관광지 검색 중(Kakao Local)...")
    raw["attractions"] = search_places(
        kakao, city, "관광지", "관광명소", ATTRACTION_CATEGORY, "attraction_search", errors)

    # [4/4] LLM 최종 리포트 (Markdown)
    print("[4/4] 최종 리포트 생성 중(LLM)...")
    try:
        body = gemini.generate_report(travel_date, rec, raw["restaurants"], raw["attractions"])
        print(" - 리포트 생성 완료")
    except LLMError as e:
        print(f" - 오류: {e.message}")
        print(" - 기본 템플릿으로 리포트를 작성합니다.")
        add_error(errors, "report", e.err_type, e.message)
        body = build_fallback_report(travel_date, rec, raw["restaurants"], raw["attractions"])

    report = body.rstrip() + "\n\n" + format_errors_section(errors) + "\n"

    # 결과 저장 (리포트 단계 오류까지 포함되도록 마지막에 저장)
    save_json(raw_path, raw)
    report_path.write_text(report, encoding="utf-8")

    print(f"완료! {os.path.relpath(report_path)} 를 확인하세요.")
    print(f"     원본 데이터: {os.path.relpath(raw_path)}")


if __name__ == "__main__":
    main()
