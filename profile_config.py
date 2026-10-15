import os
import json
from pathlib import Path

import yaml


REQUIRED_FIELDS = (
    "degree",
    "job_type",
    "directions",
    "skills",
    "target_roles",
    "score_component_limits",
    "score_thresholds",
)


def load_profile(path: str | Path = "profile.yaml") -> dict:
    profile_path = Path(path)
    private_json = os.environ.get("PERSONAL_PROFILE_JSON", "").strip()
    if private_json:
        try:
            profile = json.loads(private_json)
        except (ValueError, TypeError):
            raise ValueError("Private profile Secret is invalid JSON") from None
    elif not profile_path.exists():
        raise ValueError(f"找不到用户画像配置: {profile_path}")

    else:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    missing = [field for field in REQUIRED_FIELDS if field not in profile]
    if missing:
        raise ValueError(f"profile.yaml 缺少字段: {', '.join(missing)}")

    limits = profile["score_component_limits"]
    expected_components = {
        "core_direction",
        "required_skills",
        "project_evidence",
        "engineering_stack",
        "basic_criteria",
    }
    if (
        not isinstance(limits, dict)
        or set(limits) != expected_components
        or sum(limits.values()) != 100
    ):
        raise ValueError(
            "profile.yaml 的 score_component_limits 必须包含五个评分项且合计 100"
        )

    thresholds = profile["score_thresholds"]
    recommend = int(thresholds.get("recommend", 80))
    consider = int(thresholds.get("consider", 60))
    if not 0 <= consider <= recommend <= 100:
        raise ValueError("评分阈值必须满足 0 <= consider <= recommend <= 100")

    directions = [
        str(item).strip() for item in profile.get("directions", [])
        if str(item).strip()
    ]
    profile["direction"] = " / ".join(directions)
    if not profile.get("matching"):
        profile["matching"] = {
            "primary_directions": directions,
            "secondary_directions": profile.get("secondary_directions", []),
            "project_evidence": profile.get("project_evidence", []),
            "supporting_skills": profile.get("skills", []),
            "learning_targets": profile.get("learning_targets", []),
            "unverified_skills": profile.get("unverified_skills", []),
        }

    return profile


def personal_job_decision(job: dict, profile: dict) -> tuple[str, list[str]]:
    """Conservative rules: unknown requirements never count as verified."""
    import re
    policy = profile.get("selection_policy") or {}
    if not policy:
        return "eligible", []
    title = str(job.get("title") or "")
    body = str(job.get("jd_raw") or "")
    city = str(job.get("city") or "").strip()
    reasons = []
    if not title or re.search(r"面试通过|信息收集|人才库|一站式|欢迎使用", title):
        return "exclude", ["非有效职位"]
    if re.search(r"实习|internship|\bintern\b", title + " " + str(job.get("job_type") or ""), re.I):
        return "exclude", ["实习岗位"]
    if re.search(r"(?:必须|要求|需|至少)[^。\n]{0,16}实习[^。\n]{0,12}(?:月|天)|先实习.*转正", body):
        return "exclude", ["强制先实习"]
    if re.search(r"博士(?:学历|学位|研究生)?(?:及以上|起|必需)|仅限博士", body + title) and not re.search(r"硕士|本科|博士优先", body + title):
        return "exclude", ["博士硬门槛"]
    if re.search(r"(?:至少|不少于|要求|需具备|须具备)\s*[2-9二三四五六七八九]\s*年[^。\n]{0,12}(?:工作|行业)经验", body):
        return "exclude", ["工作年限不符"]
    if any(str(word).casefold() in title.casefold() for word in profile.get("excluded_title_keywords", [])):
        return "exclude", ["非目标职能"]
    if re.search(r"嵌入式|软件|算法|硬件|机械|电气|电子|临床运营|临床监查|医学事务|注册专员|生信工程师|生产技术|生产管理", title):
        return "exclude", ["偏离实验研发方向"]
    if city and city not in {"全国", "不限", "待定", "中国"}:
        if not any(c in city for c in profile.get("preferred_cities", [])):
            return "exclude", ["工作城市不符"]
    else:
        reasons.append("工作城市待核实")
    salary = str(job.get("salary") or job.get("salary_range") or "")
    if not salary:
        m = re.search(r"(?:月薪|薪资|薪酬)\s*[:：]\s*([^\n。]{1,40})", body)
        salary = m.group(1) if m else ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~—至]\s*(\d+(?:\.\d+)?)\s*([kK千万元])", salary)
    if m and not re.search(r"年|/year|annual", salary, re.I):
        unit = {"k": 1000, "千": 1000, "万": 10000, "元": 1}[m.group(3).lower()]
        low, high = float(m.group(1)) * unit, float(m.group(2)) * unit
        minimum = policy.get("minimum_monthly_salary", 0)
        if high < minimum:
            return "exclude", ["公开月薪上限低于底线"]
        if low < minimum:
            reasons.append("薪资区间跨底线，待定薪")
    else:
        reasons.append("薪资口径待核实")
    words = [str(w).casefold() for r in profile.get("target_roles", []) for w in r.get("keywords", [])]
    if not any(w in (title + " " + body).casefold() for w in words):
        if re.search(r"研究员|研发工程师|实验|研究助理", title):
            reasons.append("具体研究方向待核实")
        else:
            return "exclude", ["缺少目标岗位证据"]
    if not body.strip():
        reasons.append("完整JD待核实")
    return ("pending" if reasons else "eligible"), reasons


def select_personal_jobs(jobs: list[dict], profile: dict) -> list[dict]:
    result = []
    for job in jobs:
        status, reasons = personal_job_decision(job, profile)
        if status != "exclude":
            result.append({**job, "selection_status": status, "selection_notes": reasons})
    return result
