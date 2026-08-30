"""DataForSEO API client and provider-response normalizer."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..errors import WorkflowError
from ..io import atomic_write_json, read_json
from ..runs import register_artifact
from ..time import utc_now


KEYWORD_OVERVIEW_ENDPOINT = "/v3/dataforseo_labs/google/keyword_overview/live"
SERP_ADVANCED_ENDPOINT = "/v3/serp/google/organic/live/advanced"
NORMALIZER_VERSION = "1.1"
ENV_KEYS = {"DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "DATAFORSEO_BASE_URL"}


class DataForSEOError(WorkflowError):
    """Raised for provider, transport, or response failures."""


def _http_error(exc: HTTPError) -> DataForSEOError:
    """Return a credential-safe provider error with a useful response message."""

    detail = ""
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        code = payload.get("status_code")
        message = payload.get("status_message")
        if code or message:
            detail = " {} {}".format(code or "", message or "").rstrip()
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return DataForSEOError("DataForSEO HTTP error {}{}".format(exc.code, detail))


class DataForSEOClient:
    def __init__(
        self,
        login: str,
        password: str,
        base_url: str = "https://api.dataforseo.com",
        timeout: int = 60,
    ):
        if not login or not password:
            raise DataForSEOError("DataForSEO login and password are required")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "api.dataforseo.com",
            "sandbox.dataforseo.com",
        }:
            raise DataForSEOError("DataForSEO base URL must use an approved HTTPS host")
        self.login = login
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_environment(cls):
        return cls(
            login=os.environ.get("DATAFORSEO_LOGIN", ""),
            password=os.environ.get("DATAFORSEO_PASSWORD", ""),
            base_url=os.environ.get("DATAFORSEO_BASE_URL", "https://api.dataforseo.com"),
        )

    def post(self, endpoint: str, tasks: Sequence[dict]) -> dict:
        credentials = base64.b64encode(
            "{}:{}".format(self.login, self.password).encode("utf-8")
        ).decode("ascii")
        request = Request(
            self.base_url + endpoint,
            data=json.dumps(list(tasks)).encode("utf-8"),
            headers={
                "Authorization": "Basic {}".format(credentials),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "seobility-comparison-workflow/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise _http_error(exc) from exc
        except (URLError, TimeoutError) as exc:
            raise DataForSEOError(
                "DataForSEO request failed: {}".format(getattr(exc, "reason", str(exc)))
            ) from exc
        except json.JSONDecodeError as exc:
            raise DataForSEOError("DataForSEO returned invalid JSON") from exc
        _assert_success(payload)
        return payload

    def get(self, endpoint: str) -> dict:
        credentials = base64.b64encode(
            "{}:{}".format(self.login, self.password).encode("utf-8")
        ).decode("ascii")
        request = Request(
            self.base_url + endpoint,
            headers={
                "Authorization": "Basic {}".format(credentials),
                "Accept": "application/json",
                "User-Agent": "seobility-comparison-workflow/0.1",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise _http_error(exc) from exc
        except (URLError, TimeoutError) as exc:
            raise DataForSEOError(
                "DataForSEO request failed: {}".format(getattr(exc, "reason", str(exc)))
            ) from exc
        except json.JSONDecodeError as exc:
            raise DataForSEOError("DataForSEO returned invalid JSON") from exc
        _assert_success(payload)
        return payload

    def user_data(self) -> dict:
        return self.get("/v3/appendix/user_data")

    def keyword_overview(
        self,
        keywords: Sequence[str],
        location_name: str,
        language_code: str,
    ) -> dict:
        if not 1 <= len(keywords) <= 700:
            raise DataForSEOError("Keyword Overview accepts between 1 and 700 keywords")
        return self.post(
            KEYWORD_OVERVIEW_ENDPOINT,
            [
                {
                    "keywords": list(keywords),
                    "location_name": location_name,
                    "language_code": language_code,
                    "include_serp_info": False,
                }
            ],
        )

    def serp_live_advanced(
        self,
        keyword: str,
        location_name: str,
        language_code: str,
        depth: int = 10,
    ) -> dict:
        if not 1 <= depth <= 200:
            raise DataForSEOError("SERP depth must be between 1 and 200")
        return self.post(
            SERP_ADVANCED_ENDPOINT,
            [
                {
                    "keyword": keyword,
                    "location_name": location_name,
                    "language_code": language_code,
                    "device": "desktop",
                    "depth": depth,
                }
            ],
        )


def _assert_success(payload: dict) -> None:
    if payload.get("status_code") != 20000:
        raise DataForSEOError(
            "DataForSEO response failed: {} {}".format(
                payload.get("status_code"), payload.get("status_message")
            )
        )
    failed_tasks = [
        task for task in payload.get("tasks", []) if task.get("status_code") != 20000
    ]
    if failed_tasks:
        task = failed_tasks[0]
        raise DataForSEOError(
            "DataForSEO task failed: {} {}".format(
                task.get("status_code"), task.get("status_message")
            )
        )


def _task_results(payload: dict) -> Iterable[tuple]:
    _assert_success(payload)
    for task in payload.get("tasks", []):
        for result in task.get("result") or []:
            yield task, result


def _keyword_overview_results(payload: dict) -> Iterable[tuple]:
    """Yield keyword rows from both fixture and current production shapes."""

    for task, result in _task_results(payload):
        items = result.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    yield task, item
        else:
            yield task, result


def _task_metadata(payload: dict) -> tuple:
    _assert_success(payload)
    request_ids = [task["id"] for task in payload.get("tasks", []) if task.get("id")]
    total_cost = sum(float(task.get("cost") or 0) for task in payload.get("tasks", []))
    return request_ids, total_cost


def _intent(value: Optional[str]) -> str:
    normalized = (value or "unknown").lower()
    return normalized if normalized in {
        "informational", "commercial", "transactional", "navigational", "mixed"
    } else "unknown"


def _result_type(value: str) -> Optional[str]:
    return {
        "organic": "organic",
        "paid": "paid",
        "featured_snippet": "featured_snippet",
        "video": "video",
    }.get(value)


def normalize_dataforseo(
    run_id: str,
    keyword_overview_response: dict,
    serp_responses: Sequence[dict],
    provider_name: str = "dataforseo_api",
    raw_response_paths: Optional[Sequence[str]] = None,
    generated_at: Optional[str] = None,
    provider_mode: str = "live",
) -> dict:
    if provider_name not in {"dataforseo_api", "dataforseo_mcp"}:
        raise DataForSEOError("provider_name must be dataforseo_api or dataforseo_mcp")
    timestamp = generated_at or utc_now()
    queries: Dict[str, dict] = {}
    request_ids: List[str] = []
    total_cost = 0.0

    overview_ids, overview_cost = _task_metadata(keyword_overview_response)
    request_ids.extend(overview_ids)
    total_cost += overview_cost
    for task, item in _keyword_overview_results(keyword_overview_response):
        keyword = (item.get("keyword") or "").strip().lower()
        if not keyword:
            continue
        keyword_info = item.get("keyword_info") or {}
        intent_info = item.get("search_intent_info") or {}
        queries[keyword] = {
            "keyword": keyword,
            "intent": _intent(intent_info.get("main_intent")),
            "search_volume": keyword_info.get("search_volume"),
            "cpc": keyword_info.get("cpc"),
            "competition": keyword_info.get("competition"),
            "results": [],
        }

    related_questions = []
    for payload in serp_responses:
        serp_ids, serp_cost = _task_metadata(payload)
        request_ids.extend(serp_ids)
        total_cost += serp_cost
        for task, result in _task_results(payload):
            keyword = (
                result.get("keyword")
                or (task.get("data") or {}).get("keyword")
                or ""
            ).strip().lower()
            if not keyword:
                continue
            query = queries.setdefault(
                keyword,
                {
                    "keyword": keyword,
                    "intent": "unknown",
                    "search_volume": None,
                    "cpc": None,
                    "competition": None,
                    "results": [],
                },
            )
            for item in result.get("items") or []:
                item_type = item.get("type", "")
                normalized_type = _result_type(item_type)
                if normalized_type and item.get("url") and item.get("title"):
                    rank = item.get("rank_absolute") or item.get("rank_group")
                    if isinstance(rank, int) and rank >= 1:
                        query["results"].append(
                            {
                                "rank": rank,
                                "title": item["title"],
                                "url": item["url"],
                                "domain": item.get("domain") or urlparse(item["url"]).hostname or "unknown",
                                "result_type": normalized_type,
                            }
                        )
                if item_type == "people_also_ask":
                    for question in item.get("items") or []:
                        text = question.get("title") or question.get("question")
                        if text and text not in related_questions:
                            related_questions.append(text)

    for query in queries.values():
        query["results"].sort(key=lambda item: item["rank"])

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "provider": {
            "name": provider_name,
            "mode": provider_mode,
            "request_id": ",".join(dict.fromkeys(request_ids)) or None,
            "endpoints": [KEYWORD_OVERVIEW_ENDPOINT, SERP_ADVANCED_ENDPOINT],
            "raw_response_paths": list(raw_response_paths or []),
            "total_cost": round(total_cost, 6),
            "normalized_at": timestamp,
            "normalizer_version": NORMALIZER_VERSION,
        },
        "generated_at": timestamp,
        "queries": list(queries.values()),
        "related_questions": related_questions,
    }


def load_dataforseo_env(path: Path) -> None:
    """Load only DataForSEO keys from a simple .env file without executing it."""

    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise DataForSEOError("Missing environment file: {}".format(path)) from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DataForSEOError(
                "Invalid .env entry at {}:{}".format(path, line_number)
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def check_dataforseo_connection(env_file: Path = Path(".env")) -> dict:
    load_dataforseo_env(env_file)
    payload = DataForSEOClient.from_environment().user_data()
    task = (payload.get("tasks") or [{}])[0]
    result = (task.get("result") or [{}])[0]
    return {
        "status": "connected",
        "api_status_code": payload.get("status_code"),
        "api_status_message": payload.get("status_message"),
        "balance_available": bool((result.get("money") or {}).get("balance", 0) > 0),
    }


def collect_dataforseo_mvp(
    run_dir: Path,
    keywords: Sequence[str],
    location_name: Optional[str] = None,
    language_code: Optional[str] = None,
    depth: int = 10,
    sandbox: bool = False,
    confirm_live_costs: bool = False,
    env_file: Path = Path(".env"),
    generated_at: Optional[str] = None,
) -> Path:
    """Collect DataForSEO evidence for the simplified input.json-based MVP."""

    if not sandbox and not confirm_live_costs:
        raise DataForSEOError("Live DataForSEO collection requires explicit cost confirmation")
    run_dir = Path(run_dir)
    run_input = read_json(run_dir / "input.json")
    normalized_keywords = list(dict.fromkeys(item.strip() for item in keywords if item.strip()))
    if not normalized_keywords:
        raise DataForSEOError("At least one keyword is required")
    market = location_name or run_input.get("market")
    language = language_code or run_input.get("language") or "en"
    if not market:
        raise DataForSEOError("A location is required in input.json or --location")

    load_dataforseo_env(env_file)
    client = DataForSEOClient(
        login=os.environ.get("DATAFORSEO_LOGIN", ""),
        password=os.environ.get("DATAFORSEO_PASSWORD", ""),
        base_url=(
            "https://sandbox.dataforseo.com"
            if sandbox
            else os.environ.get("DATAFORSEO_BASE_URL", "https://api.dataforseo.com")
        ),
    )
    timestamp = generated_at or utc_now()
    overview = client.keyword_overview(normalized_keywords, market, language)
    serp_payloads = [
        client.serp_live_advanced(keyword, market, language, depth)
        for keyword in normalized_keywords
    ]
    collection_id = timestamp.replace(":", "").replace("-", "").lower()
    raw_dir = run_dir / "research" / "raw" / "dataforseo" / collection_id
    raw_dir.mkdir(parents=True, exist_ok=False)
    overview_path = raw_dir / "keyword-overview.json"
    atomic_write_json(overview_path, overview)
    serp_paths = []
    for index, payload in enumerate(serp_payloads, start=1):
        path = raw_dir / "serp-{:02d}.json".format(index)
        atomic_write_json(path, payload)
        serp_paths.append(path)

    output_path = run_dir / "research" / "dataforseo.json"
    if output_path.exists():
        raise DataForSEOError(
            "DataForSEO MVP research already exists; use a new run directory"
        )
    raw_paths = [
        path.relative_to(run_dir).as_posix() for path in [overview_path] + serp_paths
    ]
    normalized = normalize_dataforseo(
        run_id=run_dir.name,
        keyword_overview_response=overview,
        serp_responses=serp_payloads,
        provider_name="dataforseo_api",
        raw_response_paths=raw_paths,
        generated_at=timestamp,
        provider_mode="sandbox" if sandbox else "live",
    )
    normalized["request"] = {
        "keywords": normalized_keywords,
        "location_name": market,
        "language_code": language,
        "device": "desktop",
        "depth": depth,
    }
    atomic_write_json(output_path, normalized)
    return output_path


def normalize_dataforseo_files(
    run_dir: Path,
    keyword_response_path: Path,
    serp_response_paths: Sequence[Path],
    provider_name: str = "dataforseo_api",
    generated_at: Optional[str] = None,
) -> Path:
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    raw_paths = []
    for path in [Path(keyword_response_path)] + [Path(item) for item in serp_response_paths]:
        try:
            raw_paths.append(path.resolve().relative_to(run_dir.resolve()).as_posix())
        except ValueError:
            if run.get("data_mode") == "live":
                raise DataForSEOError(
                    "Live raw responses must be retained inside the run directory"
                )
            raw_paths.append(str(path.resolve()))
    normalized = normalize_dataforseo(
        run_id=run["run_id"],
        keyword_overview_response=read_json(Path(keyword_response_path)),
        serp_responses=[read_json(Path(path)) for path in serp_response_paths],
        provider_name=provider_name,
        raw_response_paths=raw_paths,
        generated_at=generated_at,
    )
    output_path = run_dir / "research" / "serp.json"
    if output_path.exists():
        raise DataForSEOError("SERP research already exists; start a new run or version the artifact")
    atomic_write_json(output_path, normalized)
    register_artifact(
        run_dir,
        "serp_research",
        "research/serp.json",
        1,
        created_at=normalized["generated_at"],
    )
    return output_path


def collect_dataforseo(
    run_dir: Path,
    keywords: Sequence[str],
    location_name: str,
    language_code: str,
    depth: int = 10,
    confirm_live_costs: bool = False,
) -> Path:
    if not confirm_live_costs:
        raise DataForSEOError("Live DataForSEO collection requires explicit cost confirmation")
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    if run.get("data_mode") != "live":
        raise DataForSEOError("Live DataForSEO calls require run data_mode=live")
    client = DataForSEOClient.from_environment()
    timestamp = utc_now()
    overview = client.keyword_overview(keywords, location_name, language_code)
    serp_payloads = [
        client.serp_live_advanced(keyword, location_name, language_code, depth)
        for keyword in keywords
    ]
    collection_id = timestamp.replace(":", "").replace("-", "").lower()
    raw_dir = run_dir / "research" / "raw" / "dataforseo" / collection_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    overview_path = raw_dir / "keyword-overview.json"
    atomic_write_json(overview_path, overview)
    serp_paths = []
    for index, payload in enumerate(serp_payloads, start=1):
        path = raw_dir / "serp-{:02d}.json".format(index)
        atomic_write_json(path, payload)
        serp_paths.append(path)
    for path in [overview_path] + serp_paths:
        register_artifact(
            run_dir,
            "dataforseo_raw_response",
            path.relative_to(run_dir).as_posix(),
            1,
            created_at=timestamp,
        )
    return normalize_dataforseo_files(
        run_dir,
        overview_path,
        serp_paths,
        provider_name="dataforseo_api",
        generated_at=timestamp,
    )
