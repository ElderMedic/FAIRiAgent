"""
FAIR-DS API Parser - 解析真实的 FAIR-DS API 返回数据

API Version: Latest (January 2026)
Endpoints:
    - GET /api/terms - Get all terms or filter by label/definition
    - GET /api/package - Get all packages or specific package by name
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class FAIRDSAPIParser:
    """
    解析 FAIR-DS API 返回的数据结构
    
    FAIR-DS 使用 ISA (Investigation-Study-Assay) 模型，包含5个 ISA sheets:
    - Investigation: 项目级别元数据
    - Study: 研究级别元数据
    - ObservationUnit: 观察单元级别元数据
    - Sample: 样本级别元数据（字段最多）
    - Assay: 实验/分析级别元数据
    """
    
    # ISA Sheets in hierarchy order
    ISA_SHEETS = ["investigation", "study", "observationunit", "sample", "assay"]
    
    @staticmethod
    def parse_terms_response(api_response: Any) -> Dict[str, Dict[str, Any]]:
        """
        解析 /api/terms 返回的数据
        
        API 格式:
        {
            "total": 892,
            "terms": {
                "study title": {
                    "label": "study title",
                    "syntax": "{text}",
                    "example": "...",
                    "definition": "...",
                    "regex": "...",
                    "url": "..."
                },
                ...
            }
        }
        
        返回: Dictionary mapping term names to term details
        """
        if isinstance(api_response, dict) and "terms" in api_response:
            terms = api_response["terms"]
            if isinstance(terms, dict):
                logger.info(f"✅ Parsed {len(terms)} terms from FAIR-DS API")
                return terms
        
        logger.warning(f"⚠️ Could not parse terms from API response. Type: {type(api_response)}")
        return {}
    
    @staticmethod
    def parse_package_list_response(api_response: Any) -> List[str]:
        """
        解析 /api/package 返回的包列表
        
        API 格式 (无 name 参数时):
        {
            "message": "No package name specified. Available packages listed below.",
            "packages": ["default", "miappe", "soil", ...],
            "example": "/api/package?name=soil"
        }
        
        返回: List of package names
        """
        if isinstance(api_response, dict) and "packages" in api_response:
            packages = api_response["packages"]
            if isinstance(packages, list):
                logger.info(f"✅ Parsed {len(packages)} available packages")
                return packages
        
        logger.warning(f"⚠️ Could not parse package list. Type: {type(api_response)}")
        return []
    
    @staticmethod
    def parse_package_response(api_response: Any) -> Dict[str, Any]:
        """
        解析 /api/package?name={name} 返回的包数据
        
        API 格式:
        {
            "packageName": "miappe",
            "itemCount": 63,
            "metadata": [
                {
                    "definition": null,
                    "sheetName": "Study",
                    "packageName": "miappe",
                    "requirement": "MANDATORY",
                    "label": "start date of study",
                    "term": {
                        "label": "...",
                        "syntax": "{date}",
                        "example": "...",
                        "definition": "...",
                        "regex": "...",
                        "url": "..."
                    }
                },
                ...
            ]
        }
        
        返回: Parsed package data
        """
        if isinstance(api_response, dict):
            if "metadata" in api_response and isinstance(api_response["metadata"], list):
                logger.info(
                    f"✅ Parsed package '{api_response.get('packageName', 'unknown')}' "
                    f"with {api_response.get('itemCount', len(api_response['metadata']))} fields"
                )
                return api_response
        
        logger.warning(f"⚠️ Could not parse package response. Type: {type(api_response)}")
        return {}
    
    @staticmethod
    def group_fields_by_sheet(
        fields: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        将字段按 ISA sheet 分组
        
        Args:
            fields: 字段列表（来自 package 响应的 metadata）
            
        Returns:
            按 sheet 名称分组的字段字典
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        
        for field in fields:
            sheet = field.get("sheetName", "Unknown")
            if sheet not in grouped:
                grouped[sheet] = []
            grouped[sheet].append(field)
        
        return grouped
    
    @staticmethod
    def get_mandatory_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """获取必需字段"""
        return [f for f in fields if f.get("requirement") == "MANDATORY"]
    
    @staticmethod
    def get_optional_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """获取可选字段（包括 OPTIONAL 和 RECOMMENDED）"""
        return [f for f in fields if f.get("requirement") != "MANDATORY"]
    
    @staticmethod
    def get_fields_by_requirement(
        fields: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        将字段按 requirement level 分组
        
        Returns:
            {
                "mandatory": [...],
                "recommended": [...],
                "optional": [...]
            }
        """
        result = {
            "mandatory": [],
            "recommended": [],
            "optional": []
        }
        
        for field in fields:
            req = field.get("requirement", "OPTIONAL").upper()
            if req == "MANDATORY":
                result["mandatory"].append(field)
            elif req == "RECOMMENDED":
                result["recommended"].append(field)
            else:
                result["optional"].append(field)
        
        return result
    
    @staticmethod
    def get_fields_by_sheet_and_requirement(
        fields: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        将字段按 ISA sheet 和 requirement level 分组
        
        Returns:
            {
                "Investigation": {"mandatory": [...], "optional": [...]},
                "Study": {"mandatory": [...], "optional": [...]},
                ...
            }
        """
        result: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        
        for field in fields:
            sheet = field.get("sheetName", "Unknown")
            req = field.get("requirement", "OPTIONAL").upper()
            
            if sheet not in result:
                result[sheet] = {"mandatory": [], "recommended": [], "optional": []}
            
            if req == "MANDATORY":
                result[sheet]["mandatory"].append(field)
            elif req == "RECOMMENDED":
                result[sheet]["recommended"].append(field)
            else:
                result[sheet]["optional"].append(field)
        
        return result
    
    @staticmethod
    def extract_field_info(field: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 package field 中提取关键信息
        
        输入格式（来自 /api/package?name={name}）：
        {
            "label": "study title",
            "sheetName": "Study",
            "packageName": "miappe",
            "requirement": "MANDATORY",
            "definition": "...",
            "term": {
                "label": "study title",
                "syntax": "{text}",
                "example": "...",
                "definition": "...",
                "regex": "...",
                "url": "http://..."
            }
        }
        
        返回标准化的字段信息
        """
        term = field.get("term", {})
        
        return {
            "name": field.get("label", ""),
            "label": field.get("label", ""),
            "definition": term.get("definition", "") or field.get("definition", ""),
            "required": field.get("requirement") == "MANDATORY",
            "requirement": field.get("requirement", "OPTIONAL"),
            "package": field.get("packageName", ""),
            "isa_sheet": field.get("sheetName", "").lower(),
            "sheet": field.get("sheetName", ""),
            "syntax": term.get("syntax", ""),
            "example": term.get("example", ""),
            "regex": term.get("regex", ""),
            "ontology_uri": term.get("url", ""),
            "data_type": FAIRDSAPIParser._infer_data_type(term),
            "preferred_unit": term.get("preferredUnit", ""),
        }
    
    @staticmethod
    def extract_term_info(term_name: str, term: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 term 中提取关键信息
        
        输入格式（来自 /api/terms 或 /api/terms?label={label}）：
        {
            "label": "temperature",
            "syntax": "{number}",
            "example": "25 °C",
            "preferredUnit": "°C",
            "definition": "temperature of the sample at time of sampling",
            "regex": "...",
            "url": "https://..."
        }
        
        返回标准化的术语信息
        """
        return {
            "name": term_name,
            "label": term.get("label", term_name),
            "definition": term.get("definition", ""),
            "syntax": term.get("syntax", ""),
            "example": term.get("example", ""),
            "preferred_unit": term.get("preferredUnit", ""),
            "regex": term.get("regex", ""),
            "ontology_uri": term.get("url", ""),
            "data_type": FAIRDSAPIParser._infer_data_type(term),
            "is_file": term.get("file", False),
            "is_date": term.get("date", False),
            "is_datetime": term.get("dateTime", False),
        }
    
    @staticmethod
    def _infer_data_type(term: Dict[str, Any]) -> str:
        """从 term 信息推断数据类型"""
        if term.get("file"):
            return "file"
        elif term.get("dateTime"):
            return "datetime"
        elif term.get("date"):
            return "date"
        
        syntax = term.get("syntax", "")
        if "{number}" in syntax or "{float}" in syntax:
            return "number"
        elif "{date}" in syntax:
            return "date"
        elif "{id}" in syntax:
            return "identifier"
        elif "{text}" in syntax:
            return "text"
        
        return "string"
    
    @staticmethod
    def get_package_summary(package_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成包的摘要信息
        
        Args:
            package_data: /api/package?name={name} 的响应
            
        Returns:
            摘要字典
        """
        if not package_data or "metadata" not in package_data:
            return {}
        
        fields = package_data["metadata"]
        fields_by_sheet = FAIRDSAPIParser.get_fields_by_sheet_and_requirement(fields)
        
        summary = {
            "package_name": package_data.get("packageName", ""),
            "total_fields": package_data.get("itemCount", len(fields)),
            "mandatory_count": sum(
                len(sheet_data["mandatory"]) 
                for sheet_data in fields_by_sheet.values()
            ),
            "sheets": {}
        }
        
        for sheet_name, sheet_data in fields_by_sheet.items():
            summary["sheets"][sheet_name] = {
                "total": len(sheet_data["mandatory"]) + len(sheet_data["recommended"]) + len(sheet_data["optional"]),
                "mandatory": len(sheet_data["mandatory"]),
                "recommended": len(sheet_data["recommended"]),
                "optional": len(sheet_data["optional"]),
            }
        
        return summary

    # =========================================================================
    # Legacy compatibility methods (for backward compatibility)
    # =========================================================================
    
    @staticmethod
    def parse_packages_response(api_response: Any) -> Dict[str, List[Dict[str, Any]]]:
        """
        Legacy method: 解析包响应并按 sheet 分组
        
        Note: 新版 API 使用 /api/package?name={name} 获取特定包，
        此方法保留用于向后兼容。
        """
        if isinstance(api_response, dict) and "metadata" in api_response:
            fields = api_response["metadata"]
            if isinstance(fields, list):
                return FAIRDSAPIParser.group_fields_by_sheet(fields)
        
        return {}
    
    @staticmethod
    def get_all_package_names(packages_by_sheet: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        获取所有唯一的 packageName 及其统计信息
        
        Note: 新版 API 可以直接调用 /api/package 获取包列表
        """
        package_stats = {}
        
        for sheet_name, fields in packages_by_sheet.items():
            for field in fields:
                pkg_name = field.get("packageName", "")
                if pkg_name not in package_stats:
                    package_stats[pkg_name] = {
                        "name": pkg_name,
                        "field_count": 0,
                        "mandatory_count": 0,
                        "optional_count": 0,
                        "sheets": set(),
                    }
                
                package_stats[pkg_name]["field_count"] += 1
                package_stats[pkg_name]["sheets"].add(sheet_name)
                
                if field.get("requirement") == "MANDATORY":
                    package_stats[pkg_name]["mandatory_count"] += 1
                else:
                    package_stats[pkg_name]["optional_count"] += 1
        
        result = []
        for pkg_name, stats in package_stats.items():
            stats["sheets"] = list(stats["sheets"])
            result.append(stats)
        
        result.sort(key=lambda x: x["field_count"], reverse=True)
        return result
    
    @staticmethod
    def get_fields_by_package(
        packages_by_sheet: Dict[str, List[Dict[str, Any]]],
        package_names: List[str]
    ) -> List[Dict[str, Any]]:
        """
        获取指定 packages 的所有字段
        
        Note: 新版 API 建议直接使用 /api/package?name={name} 获取特定包
        """
        all_fields = []
        seen_labels = set()
        
        for sheet_name, fields in packages_by_sheet.items():
            for field in fields:
                if field.get("packageName") in package_names:
                    label = field.get("label")
                    if label and label not in seen_labels:
                        seen_labels.add(label)
                        all_fields.append(field)
        
        return all_fields
    
    @staticmethod
    def get_fields_by_package_and_isa_sheet(
        packages_by_sheet: Dict[str, List[Dict[str, Any]]],
        package_names: List[str]
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        获取指定 packages 的所有字段，按 ISA sheet 分组
        
        Note: 新版 API 建议直接使用 /api/package?name={name}，
        然后用 get_fields_by_sheet_and_requirement() 分组
        """
        result = {sheet: {"mandatory": [], "optional": []} for sheet in FAIRDSAPIParser.ISA_SHEETS}
        seen_labels_by_sheet = {sheet: set() for sheet in FAIRDSAPIParser.ISA_SHEETS}
        
        for sheet_name, fields in packages_by_sheet.items():
            normalized_sheet = sheet_name.lower()
            if normalized_sheet not in FAIRDSAPIParser.ISA_SHEETS:
                continue
            
            for field in fields:
                if field.get("packageName") in package_names:
                    label = field.get("label")
                    requirement = field.get("requirement", "").upper()
                    
                    if label and label not in seen_labels_by_sheet[normalized_sheet]:
                        seen_labels_by_sheet[normalized_sheet].add(label)
                        
                        if requirement == "MANDATORY":
                            result[normalized_sheet]["mandatory"].append(field)
                        else:
                            result[normalized_sheet]["optional"].append(field)
        
        return result
