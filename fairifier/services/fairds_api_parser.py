"""
FAIR-DS API Parser - 解析真实的 FAIR-DS API 返回数据

基于 FAIR-DS 官方文档：https://docs.fairbydesign.nl/docs/fairdatastation/tutorials/api.html
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class FAIRDSAPIParser:
    """
    解析 FAIR-DS API 返回的数据结构
    
    FAIR-DS 使用 ISA (Investigation-Study-Assay) 模型，包含5个 packages:
    - investigation: 项目级别元数据
    - study: 研究级别元数据
    - sample: 样本级别元数据（字段最多）
    - assay: 实验/分析级别元数据
    - observationunit: 观察单元级别元数据
    """
    
    @staticmethod
    def parse_terms_response(api_response: Any) -> List[Dict[str, Any]]:
        """
        解析 /api/terms 返回的数据
        
        接收格式：
        - 原始 API 格式:
          {
            "total": 892,
            "terms": {
              "study title": {...},
              ...
            }
          }
        - 或 FAIRDataStationClient 已处理的格式: list 或 dict
        
        返回: 所有 terms 的列表
        """
        # 如果已经是列表，直接返回
        if isinstance(api_response, list):
            logger.info(f"✅ Parsed {len(api_response)} terms from FAIR-DS API (list format)")
            return api_response
        
        # 如果是字典，尝试提取 terms
        if isinstance(api_response, dict):
            if "terms" in api_response:
                terms_dict = api_response["terms"]
                # 转换为列表
                if isinstance(terms_dict, dict):
                    terms_list = list(terms_dict.values())
                else:
                    terms_list = terms_dict if isinstance(terms_dict, list) else []
                logger.info(f"✅ Parsed {len(terms_list)} terms from FAIR-DS API (dict format)")
                return terms_list
        
        logger.warning(f"⚠️  Could not parse terms from API response. Type: {type(api_response)}")
        return []
    
    @staticmethod
    def parse_packages_response(api_response: Any) -> Dict[str, List[Dict[str, Any]]]:
        """
        解析 /api/packages 返回的数据
        
        新版 API 格式 (2026+):
        {
          "total": 5,
          "totalMetadataItems": 2689,
          "metadata": {
            "investigation": {
              "name": "investigation",
              "displayName": "Investigation",
              "description": "...",
              "hierarchyOrder": 1,
              "metadata": [...]  # Fields are here
            },
            ...
          }
        }
        
        旧版 API 格式:
        {
          "total": 5,
          "packages": {
            "investigation": [...],  # Fields directly in list
            ...
          }
        }
        """
        packages = {}
        
        if isinstance(api_response, dict):
            # New API format: metadata[sheet]["metadata"] contains fields
            if "metadata" in api_response and isinstance(api_response["metadata"], dict):
                metadata = api_response["metadata"]
                # Check if it's the new format (each sheet has 'metadata' key with fields)
                first_sheet = next(iter(metadata.values()), None) if metadata else None
                if first_sheet and isinstance(first_sheet, dict) and "metadata" in first_sheet:
                    # New format: extract fields from metadata[sheet]["metadata"]
                    for sheet_name, sheet_info in metadata.items():
                        if isinstance(sheet_info, dict) and "metadata" in sheet_info:
                            packages[sheet_name.lower()] = sheet_info["metadata"]
                    logger.info(f"✅ Parsed packages from FAIR-DS API (new format):")
                else:
                    # Old format where metadata[sheet] is directly a list of fields
                    packages = {k.lower(): v for k, v in metadata.items() if isinstance(v, list)}
                    logger.info(f"✅ Parsed packages from FAIR-DS API (metadata format):")
            # Old API format: packages[sheet] contains fields directly
            elif "packages" in api_response:
                packages = {k.lower(): v for k, v in api_response["packages"].items() if isinstance(v, list)}
                logger.info(f"✅ Parsed packages from FAIR-DS API (packages format):")
        # Fallback: if directly a list
        elif isinstance(api_response, list):
            # 按 sheetName 分组
            for item in api_response:
                sheet_name = item.get("sheetName", "").lower()
                if sheet_name not in packages:
                    packages[sheet_name] = []
                packages[sheet_name].append(item)
            logger.info(f"✅ Parsed {len(packages)} packages from list format:")
        
        # 统计
        if packages:
            for pkg_name, fields in packages.items():
                if isinstance(fields, list):
                    mandatory_count = sum(1 for f in fields if f.get("requirement") == "MANDATORY")
                    logger.info(f"      {pkg_name}: {len(fields)} fields ({mandatory_count} mandatory)")
        else:
            logger.error(f"❌ Failed to parse packages. Response type: {type(api_response)}")
            logger.error(f"   Response keys: {api_response.keys() if isinstance(api_response, dict) else 'N/A'}")
        
        return packages
    
    @staticmethod
    def get_mandatory_fields(package_fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """获取包中的必需字段"""
        return [f for f in package_fields if f.get("requirement") == "MANDATORY"]
    
    @staticmethod
    def get_optional_fields(package_fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """获取包中的可选字段"""
        return [f for f in package_fields if f.get("requirement") != "MANDATORY"]
    
    @staticmethod
    def get_all_package_names(packages_by_sheet: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        获取所有唯一的 packageName 及其统计信息
        
        返回: [{"name": "soil", "field_count": 103, "mandatory_count": 7, ...}, ...]
        """
        # 收集所有 packageNames
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
                        "sample_fields": []
                    }
                
                package_stats[pkg_name]["field_count"] += 1
                package_stats[pkg_name]["sheets"].add(sheet_name)
                
                if field.get("requirement") == "MANDATORY":
                    package_stats[pkg_name]["mandatory_count"] += 1
                elif field.get("requirement") == "OPTIONAL":
                    package_stats[pkg_name]["optional_count"] += 1
                
                # 保存前3个字段作为样本
                if len(package_stats[pkg_name]["sample_fields"]) < 3:
                    package_stats[pkg_name]["sample_fields"].append({
                        "label": field.get("label"),
                        "definition": field.get("definition", "")[:100]
                    })
        
        # 转换为列表并排序
        result = []
        for pkg_name, stats in package_stats.items():
            stats["sheets"] = list(stats["sheets"])
            result.append(stats)
        
        result.sort(key=lambda x: x["field_count"], reverse=True)
        
        logger.info(f"✅ Found {len(result)} unique packages across all sheets")
        return result
    
    @staticmethod
    def get_fields_by_package(
        packages_by_sheet: Dict[str, List[Dict[str, Any]]],
        package_names: List[str]
    ) -> List[Dict[str, Any]]:
        """
        获取指定 packages 的所有字段，自动去重
        
        Args:
            packages_by_sheet: 按 sheet 分组的所有字段
            package_names: 要获取的 package 名称列表
            
        Returns:
            去重后的字段列表
        """
        all_fields = []
        seen_labels = set()
        
        for sheet_name, fields in packages_by_sheet.items():
            for field in fields:
                if field.get("packageName") in package_names:
                    label = field.get("label")
                    # 去重：同一个 label 只保留第一次出现
                    if label and label not in seen_labels:
                        seen_labels.add(label)
                        all_fields.append(field)
        
        logger.info(f"✅ Collected {len(all_fields)} unique fields from {len(package_names)} packages")
        return all_fields
    
    @staticmethod
    def get_fields_by_package_and_isa_sheet(
        packages_by_sheet: Dict[str, List[Dict[str, Any]]],
        package_names: List[str]
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """
        获取指定 packages 的所有字段，按 ISA sheet 分组，每个 sheet 内按 mandatory/optional 分类
        
        Args:
            packages_by_sheet: 按 ISA sheet 分组的所有字段
            package_names: 要获取的 package 名称列表
            
        Returns:
            按 ISA sheet 分组的字段字典:
            {
                "investigation": {"mandatory": [...], "optional": [...]},
                "study": {"mandatory": [...], "optional": [...]},
                "assay": {"mandatory": [...], "optional": [...]},
                "sample": {"mandatory": [...], "optional": [...]},
                "observationunit": {"mandatory": [...], "optional": [...]}
            }
        """
        # ISA sheet 列表
        isa_sheets = ["investigation", "study", "assay", "sample", "observationunit"]
        
        # 初始化结果结构
        result = {
            sheet: {"mandatory": [], "optional": []}
            for sheet in isa_sheets
        }
        
        # 用于去重的集合（按 ISA sheet 分别去重）
        seen_labels_by_sheet = {sheet: set() for sheet in isa_sheets}
        
        # 遍历所有 ISA sheets
        for sheet_name, fields in packages_by_sheet.items():
            # 标准化 sheet 名称（转换为小写）
            normalized_sheet = sheet_name.lower()
            
            # 如果 sheet 名称不在 ISA sheets 列表中，跳过
            if normalized_sheet not in isa_sheets:
                logger.warning(f"⚠️  Unknown ISA sheet: {sheet_name}, skipping")
                continue
            
            # 遍历该 sheet 中的所有字段
            for field in fields:
                # 检查是否属于指定的 packages
                if field.get("packageName") in package_names:
                    label = field.get("label")
                    requirement = field.get("requirement", "").upper()
                    
                    # 去重：同一个 label 在同一 ISA sheet 中只保留第一次出现
                    if label and label not in seen_labels_by_sheet[normalized_sheet]:
                        seen_labels_by_sheet[normalized_sheet].add(label)
                        
                        # 根据 requirement 分类
                        if requirement == "MANDATORY":
                            result[normalized_sheet]["mandatory"].append(field)
                        else:
                            result[normalized_sheet]["optional"].append(field)
        
        # 统计信息
        total_fields = sum(
            len(result[sheet]["mandatory"]) + len(result[sheet]["optional"])
            for sheet in isa_sheets
        )
        total_mandatory = sum(len(result[sheet]["mandatory"]) for sheet in isa_sheets)
        total_optional = sum(len(result[sheet]["optional"]) for sheet in isa_sheets)
        
        logger.info(
            f"✅ Collected {total_fields} unique fields from {len(package_names)} packages "
            f"({total_mandatory} mandatory, {total_optional} optional) "
            f"across {len([s for s in isa_sheets if result[s]['mandatory'] or result[s]['optional']])} ISA sheets"
        )
        
        return result
    
    @staticmethod
    def extract_field_info(field: Dict[str, Any]) -> Dict[str, Any]:
        """
        从 package field 中提取关键信息，包括 isa_sheet 和 package
        
        输入格式（来自 /api/packages）：
        {
          "label": "study title",
          "sheetName": "study",  # ISA sheet (investigation/study/assay/sample/observationunit)
          "packageName": "miappe",  # Package name
          "definition": "...",
          "requirement": "MANDATORY",
          "packageName": "default",
          "sheetName": "Study",
          "term": {
            "syntax": "{text}{10,}",
            "example": "...",
            "regex": ".*{10,}",
            "url": "http://schema.org/title"
          }
        }
        """
        term = field.get("term", {})
        sheet_name = field.get("sheetName", "").lower()  # Normalize to lowercase
        
        return {
            "name": field.get("label", ""),
            "definition": field.get("definition", ""),
            "required": field.get("requirement") == "MANDATORY",
            "package": field.get("packageName", ""),  # Real package from FAIR-DS
            "isa_sheet": sheet_name,  # ISA sheet: investigation/study/assay/sample/observationunit
            "syntax": term.get("syntax", ""),
            "example": term.get("example", ""),
            "regex": term.get("regex", ""),
            "ontology_uri": term.get("url", ""),
            "data_type": FAIRDSAPIParser._infer_data_type(term),
            # Keep original sheet name for reference
            "sheet": field.get("sheetName", "")
        }
    
    @staticmethod
    def _infer_data_type(term: Dict[str, Any]) -> str:
        """从 term 信息推断数据类型"""
        if term.get("file"):
            return "file"
        elif term.get("date"):
            return "date"
        elif term.get("dateTime"):
            return "datetime"
        elif term.get("regex", "").startswith("^[0-9"):
            return "number"
        else:
            return "string"

