"""Kakao Local 키워드 장소 검색 모듈 (REST, GET 방식)"""

import requests

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 카카오 카테고리 그룹 코드
RESTAURANT_CATEGORY = "FD6"  # 음식점
ATTRACTION_CATEGORY = "AT4"  # 관광명소


class PlaceSearchError(Exception):
    """장소 검색 실패 (인증/쿼터/네트워크/파싱)."""

    def __init__(self, err_type: str, message: str):
        super().__init__(message)
        self.err_type = err_type
        self.message = message


class KakaoLocalClient:
    def __init__(self, api_key: str, timeout: int = 10):
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, category_code: str | None = None, size: int = 5) -> list:
        params = {"query": query, "size": max(1, min(size, 15))}  # 카카오 size 범위: 1~15
        if category_code:
            params["category_group_code"] = category_code

        try:
            resp = requests.get(
                KAKAO_KEYWORD_URL,
                headers={"Authorization": f"KakaoAK {self.api_key}"},
                params=params,
                timeout=self.timeout,
            )
        except requests.Timeout:
            raise PlaceSearchError("NETWORK_ERROR", "장소 검색 요청 시간 초과")
        except requests.RequestException as e:
            raise PlaceSearchError("NETWORK_ERROR", f"장소 검색 네트워크 오류({type(e).__name__})")

        status = resp.status_code
        if status in (401, 403):
            raise PlaceSearchError(
                "AUTH_ERROR",
                f"인증 실패(HTTP {status}). REST API 키와 앱의 카카오맵 사용 설정을 확인하세요.",
            )
        if status == 429:
            raise PlaceSearchError("QUOTA_ERROR", "장소 검색 호출 한도 초과(HTTP 429)")
        if not resp.ok:
            raise PlaceSearchError("HTTP_ERROR", f"장소 검색 실패(HTTP {status})")

        try:
            documents = resp.json().get("documents", [])
        except ValueError:
            raise PlaceSearchError("PARSE_ERROR", "장소 검색 응답 JSON 파싱 실패")

        return [self._normalize(doc) for doc in documents]

    @staticmethod
    def _normalize(doc: dict) -> dict:
        """카카오 응답을 과제 최소 필드 형태로 정리한다."""

        def to_float(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return {
            "name": doc.get("place_name", ""),
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "category": doc.get("category_name", ""),
            "phone": doc.get("phone", ""),
            "url": doc.get("place_url", ""),
            "lat": to_float(doc.get("y")),  # 카카오 y = 위도
            "lng": to_float(doc.get("x")),  # 카카오 x = 경도
        }
