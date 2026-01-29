"""
LLM Helper - Centralized LLM interaction utilities.

Provides a unified interface for working with different LLM providers
(Ollama, OpenAI, Anthropic) and common LLM operations.
"""

import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langsmith import traceable

# Import providers conditionally
try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None

from ..config import config

logger = logging.getLogger(__name__)


def _extract_json_from_markdown(content: str) -> str:
    """Extract JSON content from markdown code blocks.
    
    Handles cases where JSON content might contain ``` markers in strings
    by finding the LAST closing ``` marker instead of the first.
    
    Args:
        content: Content that may contain markdown code fences
        
    Returns:
        Extracted JSON string without markdown fences
    """
    if "```json" in content:
        # Find the start after ```json
        start_idx = content.find("```json")
        if start_idx >= 0:
            # Start after ```json (7 chars) and any whitespace
            json_start = start_idx + 7
            # Skip leading whitespace/newlines
            while json_start < len(content) and content[json_start] in ['\n', '\r', ' ', '\t']:
                json_start += 1
            
            # Find the LAST ``` marker (from the end) to handle cases where JSON contains ``` in strings
            end_idx = content.rfind("```")
            if end_idx > json_start:
                return content[json_start:end_idx].strip()
            else:
                # Fallback: if no closing ``` found, try to extract from start to end
                return content[json_start:].strip()
    elif "```" in content:
        # Similar logic for generic code blocks
        start_idx = content.find("```")
        if start_idx >= 0:
            # Find the language identifier (if any) - skip until newline
            json_start = content.find("\n", start_idx)
            if json_start < 0:
                json_start = start_idx + 3  # Skip ```
            else:
                json_start += 1  # Skip the newline
            
            # Skip leading whitespace
            while json_start < len(content) and content[json_start] in ['\n', '\r', ' ', '\t']:
                json_start += 1
            
            # Find the NEXT ``` marker (close of FIRST code block, not the last one)
            # CRITICAL FIX: Use find() instead of rfind() to get the FIRST closing marker
            end_idx = content.find("```", json_start)
            if end_idx > json_start:
                return content[json_start:end_idx].strip()
            else:
                # No closing marker found, return rest of content
                return content[json_start:].strip()
    
    # No markdown fences found, return as-is
    return content.strip()


def _fix_json_string(content: str) -> str:
    """Fix common JSON formatting issues, including truncated JSON.
    
    Args:
        content: JSON string that may have formatting issues or be truncated
        
    Returns:
        Fixed JSON string
    """
    import re
    
    # Remove markdown code blocks if present
    content = _extract_json_from_markdown(content)
    
    # Find JSON object start
    json_start = content.find('{')
    if json_start < 0:
        return content
    
    content = content[json_start:]
    
    # Fix common JSON syntax errors:
    # More targeted fix: look for pattern ": number text" where text is not quoted
    content = re.sub(
        r'("([^"]+)":\s*)(\d+)\s+([a-zA-Z][^",}\]]+)"',
        r'\1"\3 \4"',
        content
    )
    
    # Fix pattern: ": text" where text starts with letter and is not quoted
    content = re.sub(
        r'("([^"]+)":\s*)([a-zA-Z][^",}\]]+\s+[^",}\]]+)"',
        lambda m: f'{m.group(1)}"{m.group(3)}"',
        content
    )
    
    # Try to find a complete JSON object first
    brace_count = 0
    bracket_count = 0
    last_valid_pos = -1
    in_string = False
    escape_next = False
    
    for i, char in enumerate(content):
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
        
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        
        if in_string:
            continue
        
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                last_valid_pos = i + 1
                break
        elif char == '[':
            bracket_count += 1
        elif char == ']':
            bracket_count -= 1
    
    # If we found a complete object, use it
    if last_valid_pos > 0:
        return content[:last_valid_pos]
    
    # JSON is truncated - attempt to repair it
    logger.debug(f"JSON appears truncated, attempting repair...")
    
    # Find the last complete key-value pair by looking for patterns
    # Look for: "key": "value", or "key": number, or "key": [...], or "key": {...}
    
    # Strategy 1: Find last complete property with string value ending in comma
    last_complete_pos = -1
    
    # Look for pattern: "key": "value",
    string_value_pattern = r'"[^"]+"\s*:\s*"[^"]*"\s*,'
    for match in re.finditer(string_value_pattern, content):
        last_complete_pos = max(last_complete_pos, match.end() - 1)  # Position after value, before comma
    
    # Look for pattern: "key": number,
    number_value_pattern = r'"[^"]+"\s*:\s*[\d.eE+-]+\s*,'
    for match in re.finditer(number_value_pattern, content):
        last_complete_pos = max(last_complete_pos, match.end() - 1)
    
    # Look for pattern: "key": true/false/null,
    literal_value_pattern = r'"[^"]+"\s*:\s*(?:true|false|null)\s*,'
    for match in re.finditer(literal_value_pattern, content):
        last_complete_pos = max(last_complete_pos, match.end() - 1)
    
    if last_complete_pos > 0:
        # Found a complete property, truncate there and close braces/brackets
        partial_content = content[:last_complete_pos].rstrip(',')
        
        # Count unclosed braces and brackets
        open_braces = 0
        open_brackets = 0
        in_str = False
        esc_next = False
        
        for char in partial_content:
            if esc_next:
                esc_next = False
                continue
            if char == '\\':
                esc_next = True
                continue
            if char == '"' and not esc_next:
                in_str = not in_str
                continue
            if in_str:
                continue
            if char == '{':
                open_braces += 1
            elif char == '}':
                open_braces -= 1
            elif char == '[':
                open_brackets += 1
            elif char == ']':
                open_brackets -= 1
        
        # Close arrays first (inner), then objects (outer)
        partial_content += ']' * max(0, open_brackets)
        partial_content += '}' * max(0, open_braces)
        
        logger.debug(f"Repaired truncated JSON: added {open_brackets} ] and {open_braces} }}")
        return partial_content
    
    # Strategy 2: More aggressive - find any complete value and truncate there
    # Look for last closed quote followed by comma or end
    last_quote_comma = -1
    for i in range(len(content) - 1, 0, -1):
        if content[i] == ',' and i > 0:
            # Check if this comma follows a value
            j = i - 1
            while j >= 0 and content[j] in ' \t\n\r':
                j -= 1
            if j >= 0 and content[j] in '}"0123456789]eEtrufalsn':
                last_quote_comma = i
                break
    
    if last_quote_comma > 0:
        partial_content = content[:last_quote_comma]
        
        # Count and close braces/brackets
        open_braces = partial_content.count('{') - partial_content.count('}')
        open_brackets = partial_content.count('[') - partial_content.count(']')
        
        partial_content += ']' * max(0, open_brackets)
        partial_content += '}' * max(0, open_braces)
        
        logger.debug(f"Aggressive repair: truncated at position {last_quote_comma}")
        return partial_content
    
    # Strategy 3: Last resort - just close all open braces
    open_braces = content.count('{') - content.count('}')
    open_brackets = content.count('[') - content.count(']')
    
    # Try to find and fix truncated string
    # If we're in the middle of a string value, close it
    quote_count = 0
    for i, char in enumerate(content):
        if char == '"' and (i == 0 or content[i-1] != '\\'):
            quote_count += 1
    
    if quote_count % 2 == 1:
        # Odd number of quotes - string is truncated
        # Find last quote and truncate before it
        last_quote = content.rfind('"')
        if last_quote > 0:
            # Find the key start for this value
            key_start = content.rfind('"', 0, last_quote - 1)
            if key_start > 0:
                key_start = content.rfind('"', 0, key_start)
                if key_start > 0:
                    # Find the comma before this key
                    comma_pos = content.rfind(',', 0, key_start)
                    if comma_pos > 0:
                        partial_content = content[:comma_pos]
                        open_braces = partial_content.count('{') - partial_content.count('}')
                        open_brackets = partial_content.count('[') - partial_content.count(']')
                        partial_content += ']' * max(0, open_brackets)
                        partial_content += '}' * max(0, open_braces)
                        logger.debug(f"Fixed truncated string by removing incomplete property")
                        return partial_content
    
    # Final fallback - close what we have
    content += ']' * max(0, open_brackets)
    content += '}' * max(0, open_braces)
    
    return content


def _parse_json_with_fallback(content: str) -> Optional[Dict[str, Any]]:
    """Parse JSON with multiple fallback strategies.
    
    Args:
        content: JSON string to parse
        
    Returns:
        Parsed JSON dict or None if all strategies fail
    """
    # Pre-process: Remove markdown code fences if present
    original_length = len(content)
    content = _extract_json_from_markdown(content)
    logger.debug(
        f"After fence removal: {original_length} -> {len(content)} chars, "
        f"starts with: {content[:50]}"
    )
    
    # Strategy 1: Direct parse
    try:
        result = json.loads(content)
        logger.debug(f"✅ Strategy 1 (direct parse) succeeded")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"Strategy 1 failed: {e}")
        pass
    
    # Strategy 2: Fix common issues and parse
    try:
        fixed_content = _fix_json_string(content)
        # Try to parse the fixed content
        result = json.loads(fixed_content)
        logger.debug(f"✅ Strategy 2 (fixed JSON) succeeded")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"Strategy 2 (fixed JSON) failed: {e}")
        # Log the error position for debugging
        if hasattr(e, 'pos'):
            logger.debug(f"JSON error at position {e.pos}: {fixed_content[max(0, e.pos-100):e.pos+100]}")
    
    # Strategy 3: Extract first complete JSON object
    try:
        json_start = content.find('{')
        if json_start >= 0:
            brace_count = 0
            complete_end = -1
            in_string = False
            escape_next = False
            
            for i, char in enumerate(content[json_start:], start=json_start):
                if escape_next:
                    escape_next = False
                    continue
                
                if char == '\\':
                    escape_next = True
                    continue
                
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                
                if in_string:
                    continue
                
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        complete_end = i + 1
                        break
            
            if complete_end > json_start:
                complete_json = content[json_start:complete_end]
                return json.loads(complete_json)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug(f"Complete object extraction failed: {e}")
    
    # Strategy 4: Try to extract partial JSON by removing incomplete trailing content
    try:
        json_start = content.find('{')
        if json_start >= 0:
            # Find error position (approximate)
            error_pos = len(content)
            
            # Try to find last valid property before error
            partial_content = content[json_start:error_pos]
            
            # Remove incomplete trailing content
            # Look for last complete property
            # Pattern: "key": value followed by comma
            last_comma = partial_content.rfind(',')
            if last_comma > 0:
                # Check if there's a complete property before this comma
                before_comma = partial_content[:last_comma]
                # Find the last property key before comma
                last_key_match = re.search(r'"([^"]+)":\s*[^,}]+(?=,\s*"|})', before_comma)
                if last_key_match:
                    # Extract up to and including this property
                    prop_end = last_key_match.end()
                    # Include the comma if it's there
                    if partial_content[prop_end:prop_end+1] == ',':
                        prop_end += 1
                    
                    partial_json = partial_content[:prop_end]
                    # Close braces
                    open_braces = partial_json.count('{') - partial_json.count('}')
                    if open_braces > 0:
                        partial_json += '}' * open_braces
                    
                    return json.loads(partial_json)
    except (json.JSONDecodeError, ValueError) as e:
        logger.debug(f"Partial extraction failed: {e}")
    
    return None


class LLMHelper:
    """Helper class for LLM interactions."""
    
    def __init__(self):
        self.provider = config.llm_provider
        self.model = config.llm_model
        self.llm = self._initialize_llm()
        self.llm_responses = []  # Store all LLM interactions for debugging
    
    def _log_llm_response(self, result, messages, operation_name: str):
        """Helper method to log LLM response to llm_responses list.
        
        Args:
            result: The LLM response object
            messages: The input messages sent to LLM
            operation_name: Name of the operation
        """
        try:
            # Extract content from result
            content = None
            if hasattr(result, 'content'):
                content = result.content
            elif hasattr(result, '__str__'):
                content = str(result)
            
            if content is None:
                logger.warning(f"Could not extract content from LLM result for {operation_name}")
                return
            
            # Calculate prompt length
            prompt_length = 0
            for msg in messages:
                if hasattr(msg, 'content') and msg.content:
                    prompt_length += len(str(msg.content))
            
            # Normalize operation name for consistency
            normalized_operation = operation_name.lower().replace(" ", "_").replace(".", "_")
            
            # Append to llm_responses
            self.llm_responses.append({
                "operation": normalized_operation,
                "prompt_length": prompt_length,
                "response": content,
                "timestamp": datetime.now().isoformat()
            })
            
            logger.debug(f"Logged LLM response for operation: {normalized_operation} ({len(content)} chars)")
        except Exception as e:
            # Don't fail the entire operation if logging fails
            logger.warning(f"Failed to log LLM response for {operation_name}: {e}")
    
    async def _call_llm(self, messages, stream_to_streamlit=None, operation_name="LLM Call"):
        """Helper method to call LLM with proper parameters.
        
        Supports both thinking and non-thinking modes.
        For Qwen models, enable_thinking is passed via extra_body as per official docs.
        
        Args:
            messages: List of messages to send to LLM
            stream_to_streamlit: If True, stream output to Streamlit container (if available).
                                If None, auto-detect if Streamlit container is available.
            operation_name: Name of the operation for display purposes.
        """
        enable_thinking = config.llm_enable_thinking
        
        # Extract prompt preview for display
        prompt_preview = ""
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'content'):
                prompt_preview = last_message.content[:500] if last_message.content else ""
        
        # Extract agent name from operation_name
        agent_name = "System"
        if "DocumentParser" in operation_name or "parse" in operation_name.lower():
            agent_name = "📄 Document Parser"
        elif "KnowledgeRetriever" in operation_name or "retrieve" in operation_name.lower() or "package" in operation_name.lower():
            agent_name = "🔍 Knowledge Retriever"
        elif "JSONGenerator" in operation_name or "generate" in operation_name.lower() or "json" in operation_name.lower():
            agent_name = "📝 JSON Generator"
        elif "Critic" in operation_name or "evaluate" in operation_name.lower() or "critic" in operation_name.lower():
            agent_name = "🎯 Critic"
        elif "orchestrator" in operation_name.lower() or "plan" in operation_name.lower() or "workflow" in operation_name.lower():
            agent_name = "🎼 Planner"
        
        # Auto-detect Streamlit chat container if stream_to_streamlit is None
        chat_container = None
        message_id = None
        if stream_to_streamlit is None:
            # Try to detect if we're in Streamlit mode
            try:
                from fairifier.apps.ui.streamlit_app import get_streamlit_chat_container
                chat_container = get_streamlit_chat_container()
                stream_to_streamlit = chat_container is not None
                if stream_to_streamlit:
                    # Create a new chat message
                    from fairifier.apps.ui.streamlit_app import create_chat_message
                    _, message_id = create_chat_message(agent_name, operation_name)
            except (ImportError, AttributeError):
                stream_to_streamlit = False
        elif stream_to_streamlit:
            # Explicitly requested streaming
            try:
                from fairifier.apps.ui.streamlit_app import get_streamlit_chat_container, create_chat_message
                chat_container = get_streamlit_chat_container()
                if chat_container:
                    # Create a new chat message
                    _, message_id = create_chat_message(agent_name, operation_name)
            except (ImportError, AttributeError):
                chat_container = None
                stream_to_streamlit = False
        
        # For Qwen provider, use extra_body as per official documentation
        if self.provider == "qwen":
            if enable_thinking or stream_to_streamlit:
                # Thinking mode or streaming mode: use streaming
                try:
                    # Use bind with extra_body for Qwen (as per official docs)
                    llm_with_params = self.llm.bind(
                        extra_body={"enable_thinking": True if enable_thinking else False},
                        stream=True
                    )
                    # Collect streaming response
                    content_parts = []
                    full_text = ""
                    
                    async for chunk in llm_with_params.astream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            content = chunk.content
                            content_parts.append(content)
                            full_text += content
                            
                            # Stream to Streamlit chat if available
                            if message_id:
                                try:
                                    from fairifier.apps.ui.streamlit_app import update_chat_message
                                    update_chat_message(message_id, full_text, is_streaming=True)
                                except Exception:
                                    pass  # Ignore errors in Streamlit update
                    
                    # Finalize chat message (remove cursor)
                    if message_id:
                        try:
                            from fairifier.apps.ui.streamlit_app import finalize_chat_message
                            finalize_chat_message(message_id)
                        except Exception:
                            pass
                    
                    # Create a response-like object
                    result = AIMessage(content=full_text)
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display if available
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, full_text)
                    except (ImportError, AttributeError):
                        pass
                    
                    return result
                except Exception as e:
                    logger.warning(f"Streaming failed: {e}, trying non-streaming")
                    # If streaming doesn't work, try non-streaming
                    try:
                        llm_with_params = self.llm.bind(
                            extra_body={"enable_thinking": True if enable_thinking else False}
                        )
                        result = await llm_with_params.ainvoke(messages)
                        
                        # Log LLM response
                        self._log_llm_response(result, messages, operation_name)
                        
                        # Add to Streamlit display
                        try:
                            from fairifier.apps.ui.streamlit_app import add_llm_response
                            content = result.content if hasattr(result, 'content') else str(result)
                            add_llm_response(operation_name, prompt_preview, content)
                        except (ImportError, AttributeError):
                            pass
                        return result
                    except Exception as e2:
                        logger.warning(f"Non-streaming failed: {e2}, falling back to regular call")
                        result = await self.llm.ainvoke(messages)
                        
                        # Log LLM response
                        self._log_llm_response(result, messages, operation_name)
                        
                        # Add to Streamlit display
                        try:
                            from fairifier.apps.ui.streamlit_app import add_llm_response
                            content = result.content if hasattr(result, 'content') else str(result)
                            add_llm_response(operation_name, prompt_preview, content)
                        except (ImportError, AttributeError):
                            pass
                        return result
            else:
                # Non-thinking mode: ensure enable_thinking=False
                # Qwen3 open-source models require this for non-streaming calls
                try:
                    llm_with_params = self.llm.bind(
                        extra_body={"enable_thinking": False}
                    )
                    result = await llm_with_params.ainvoke(messages)
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.warning(f"Failed to set enable_thinking=False via extra_body: {e}, using regular call")
                    result = await self.llm.ainvoke(messages)
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
        elif self.provider == "openai":
            # For OpenAI provider, support streaming if requested
            if stream_to_streamlit:
                try:
                    llm_with_params = self.llm.bind(stream=True)
                    content_parts = []
                    full_text = ""
                    
                    async for chunk in llm_with_params.astream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            content = chunk.content
                            content_parts.append(content)
                            full_text += content
                            
                            # Stream to Streamlit chat if available
                            if message_id:
                                try:
                                    from fairifier.apps.ui.streamlit_app import update_chat_message
                                    update_chat_message(message_id, full_text, is_streaming=True)
                                except Exception:
                                    pass
                    
                    # Finalize chat message (remove cursor)
                    if message_id:
                        try:
                            from fairifier.apps.ui.streamlit_app import finalize_chat_message
                            finalize_chat_message(message_id)
                        except Exception:
                            pass
                    
                    result = AIMessage(content=full_text)
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, full_text)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.warning(f"OpenAI streaming failed: {e}, falling back to regular call")
                    result = await self.llm.ainvoke(messages)
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
            else:
                result = await self.llm.ainvoke(messages)
                
                # Log LLM response
                self._log_llm_response(result, messages, operation_name)
                
                # Add to Streamlit display
                try:
                    from fairifier.apps.ui.streamlit_app import add_llm_response
                    content = result.content if hasattr(result, 'content') else str(result)
                    add_llm_response(operation_name, prompt_preview, content)
                except (ImportError, AttributeError):
                    pass
                return result
        elif self.provider == "ollama":
            # Ollama supports streaming
            if stream_to_streamlit:
                try:
                    llm_with_params = self.llm.bind(stream=True)
                    content_parts = []
                    full_text = ""
                    
                    async for chunk in llm_with_params.astream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            content = chunk.content
                            content_parts.append(content)
                            full_text += content
                            
                            # Stream to Streamlit chat if available
                            if message_id:
                                try:
                                    from fairifier.apps.ui.streamlit_app import update_chat_message
                                    update_chat_message(message_id, full_text, is_streaming=True)
                                except Exception:
                                    pass
                    
                    # Finalize chat message (remove cursor)
                    if message_id:
                        try:
                            from fairifier.apps.ui.streamlit_app import finalize_chat_message
                            finalize_chat_message(message_id)
                        except Exception:
                            pass
                    
                    result = AIMessage(content=full_text)
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, full_text)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.warning(f"Ollama streaming failed: {e}, falling back to regular call")
                    result = await self.llm.ainvoke(messages)
                    
                    # Check if result is valid
                    if not result:
                        logger.error(f"❌ Ollama returned None result for {operation_name}")
                        raise ValueError(f"Ollama returned None result")
                    
                    # Try multiple ways to get content (same as non-streaming path)
                    content = None
                    if hasattr(result, 'content'):
                        content = result.content
                    
                    if not content or len(str(content).strip()) == 0:
                        # Try response_metadata
                        if hasattr(result, 'response_metadata'):
                            metadata = result.response_metadata
                            if isinstance(metadata, dict):
                                for key in ['content', 'text', 'message', 'response']:
                                    if key in metadata and metadata[key]:
                                        content = metadata[key]
                                        logger.info(f"Found content in response_metadata['{key}']: {len(str(content))} chars")
                                        break
                        
                        # Try direct attribute access
                        if not content:
                            for attr in ['text', 'message', 'response', 'output']:
                                if hasattr(result, attr):
                                    attr_value = getattr(result, attr)
                                    if attr_value and len(str(attr_value).strip()) > 0:
                                        content = attr_value
                                        logger.info(f"Found content in result.{attr}: {len(str(content))} chars")
                                        break
                    
                    if not content or len(str(content).strip()) == 0:
                        logger.error(f"❌ Ollama returned empty content for {operation_name}")
                        logger.error(f"Result object: {result}, Type: {type(result)}")
                        if hasattr(result, 'response_metadata'):
                            logger.error(f"Response metadata: {result.response_metadata}")
                        raise ValueError(f"Ollama returned empty content")
                    
                    # If we found content from alternative source, update result.content
                    if content and (not hasattr(result, 'content') or not result.content):
                        logger.info(f"Updating result.content with content from alternative source")
                        result.content = content
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
            else:
                try:
                    result = await self.llm.ainvoke(messages)
                    
                    # Check if result is valid
                    if not result:
                        logger.error(f"❌ Ollama returned None result for {operation_name}")
                        logger.error(f"Provider: {self.provider}, Model: {self.model}, Base URL: {config.llm_base_url}")
                        raise ValueError(f"Ollama returned None result")
                    
                    # Debug: Log full result structure for ollama
                    logger.debug(f"Ollama result type: {type(result)}")
                    logger.debug(f"Ollama result attributes: {dir(result) if result else 'None'}")
                    if hasattr(result, 'response_metadata'):
                        logger.debug(f"Ollama response_metadata: {result.response_metadata}")
                    
                    # Try multiple ways to get content
                    content = None
                    if hasattr(result, 'content'):
                        content = result.content
                        logger.debug(f"Got content from result.content: {len(str(content)) if content else 0} chars")
                    
                    # If content is empty, try other attributes
                    if not content or len(str(content).strip()) == 0:
                        # Try response_metadata - ollama might store content here when truncated
                        if hasattr(result, 'response_metadata'):
                            metadata = result.response_metadata
                            logger.debug(f"Checking response_metadata: {metadata}")
                            # Some ollama responses might have content in metadata
                            if isinstance(metadata, dict):
                                # Check for common ollama metadata keys
                                for key in ['content', 'text', 'message', 'response', 'model_response', 'generated_text']:
                                    if key in metadata and metadata[key]:
                                        content = metadata[key]
                                        logger.info(f"Found content in response_metadata['{key}']: {len(str(content))} chars")
                                        break
                                
                                # Check nested structures (ollama sometimes nests content)
                                if not content:
                                    for key in ['message', 'response', 'data']:
                                        if key in metadata and isinstance(metadata[key], dict):
                                            nested = metadata[key]
                                            for nested_key in ['content', 'text', 'message', 'response']:
                                                if nested_key in nested and nested[nested_key]:
                                                    content = nested[nested_key]
                                                    logger.info(f"Found content in response_metadata['{key}']['{nested_key}']: {len(str(content))} chars")
                                                    break
                                            if content:
                                                break
                        
                        # Try direct attribute access
                        if not content:
                            for attr in ['text', 'message', 'response', 'output', 'generated_text']:
                                if hasattr(result, attr):
                                    attr_value = getattr(result, attr)
                                    if attr_value and len(str(attr_value).strip()) > 0:
                                        content = attr_value
                                        logger.info(f"Found content in result.{attr}: {len(str(content))} chars")
                                        break
                        
                        # Last resort: check if result has a __dict__ with content
                        if not content and hasattr(result, '__dict__'):
                            result_dict = result.__dict__
                            for key in ['content', 'text', 'message', 'response', 'output', 'generated_text']:
                                if key in result_dict and result_dict[key]:
                                    content = result_dict[key]
                                    logger.info(f"Found content in result.__dict__['{key}']: {len(str(content))} chars")
                                    break
                    
                    # Final check
                    if not content or len(str(content).strip()) == 0:
                        logger.error(f"❌ Ollama returned empty content for {operation_name}")
                        logger.error(f"Result object: {result}")
                        logger.error(f"Result type: {type(result)}")
                        logger.error(f"Result attributes: {dir(result) if result else 'None'}")
                        if hasattr(result, 'response_metadata'):
                            logger.error(f"Response metadata: {result.response_metadata}")
                        logger.error(f"Provider: {self.provider}, Model: {self.model}, Base URL: {config.llm_base_url}")
                        raise ValueError(f"Ollama returned empty content")
                    
                    # If we found content from alternative source, update result.content
                    if content and (not hasattr(result, 'content') or not result.content):
                        logger.info(f"Updating result.content with content from alternative source")
                        result.content = content
                    
                    # Log LLM response
                    self._log_llm_response(result, messages, operation_name)
                    
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.error(f"❌ Ollama call failed for {operation_name}: {e}")
                    logger.error(f"Provider: {self.provider}, Model: {self.model}, Base URL: {config.llm_base_url}")
                    raise
        else:
            # For other providers (anthropic), no special handling needed
            result = await self.llm.ainvoke(messages)
            
            # Log LLM response
            self._log_llm_response(result, messages, operation_name)
            
            # Add to Streamlit display if available
            try:
                from fairifier.apps.ui.streamlit_app import add_llm_response
                content = result.content if hasattr(result, 'content') else str(result)
                add_llm_response(operation_name, prompt_preview, content)
            except (ImportError, AttributeError):
                pass
            
            return result
        
    def _initialize_llm(self):
        """Initialize LLM based on provider configuration.
        
        Supported providers:
        - ollama: Local Ollama instance (default)
        - openai: OpenAI API (gpt-4, gpt-3.5-turbo, etc.)
        - qwen: Alibaba Cloud Qwen API (OpenAI-compatible)
        - anthropic: Anthropic Claude API
        """
        if self.provider == "ollama":
            if ChatOllama is None:
                raise ImportError("langchain_ollama not installed. Install with: pip install langchain-ollama")
            logger.info(f"Initializing Ollama LLM: {self.model} at {config.llm_base_url}")
            return ChatOllama(
                model=self.model,
                base_url=config.llm_base_url,
                temperature=config.llm_temperature,
                num_predict=config.llm_max_tokens,  # Limit output tokens to prevent infinite generation
            )
        elif self.provider == "openai":
            if ChatOpenAI is None:
                raise ImportError("langchain_openai not installed. Install with: pip install langchain-openai")
            if not config.llm_api_key:
                raise ValueError("LLM_API_KEY environment variable is required for OpenAI provider")
            base_url = config.llm_base_url if config.llm_base_url != "http://localhost:11434" else None
            logger.info(f"Initializing OpenAI LLM: {self.model}" + (f" at {base_url}" if base_url else ""))
            # Initialize ChatOpenAI
            # For OpenAI, enable_thinking is not a standard parameter
            return ChatOpenAI(
                model=self.model,
                api_key=config.llm_api_key,
                base_url=base_url,  # None uses default OpenAI API
                temperature=config.llm_temperature,
                max_tokens=config.llm_max_tokens,  # Limit output tokens
            )
        elif self.provider == "qwen":
            if ChatOpenAI is None:
                raise ImportError("langchain_openai not installed. Install with: pip install langchain-openai")
            if not config.llm_api_key:
                raise ValueError("LLM_API_KEY environment variable is required for Qwen provider")
            # Qwen uses OpenAI-compatible API
            base_url = config.llm_base_url
            logger.info(f"Initializing Qwen LLM: {self.model} at {base_url}")
            # Initialize ChatOpenAI for Qwen
            # Note: enable_thinking is passed via extra_body in _call_llm, not here
            # This is because extra_body needs to be set per-call, not at initialization
            return ChatOpenAI(
                model=self.model,
                api_key=config.llm_api_key,
                base_url=base_url,
                temperature=config.llm_temperature,
                max_tokens=config.llm_max_tokens,  # Limit output tokens
            )
        elif self.provider == "anthropic" or self.provider == "claude":
            if ChatAnthropic is None:
                raise ImportError("langchain_anthropic not installed. Install with: pip install langchain-anthropic")
            if not config.llm_api_key:
                raise ValueError("LLM_API_KEY environment variable is required for Anthropic provider")
            logger.info(f"Initializing Anthropic Claude LLM: {self.model}")
            return ChatAnthropic(
                model=self.model,
                api_key=config.llm_api_key,
                temperature=config.llm_temperature,
                max_tokens=config.llm_max_tokens,  # Limit output tokens
            )
        else:
            raise ValueError(
                f"Unsupported LLM provider: {self.provider}. "
                f"Supported providers: ollama, openai, qwen, anthropic (claude)"
            )
    
    @traceable(name="LLM.ExtractDocumentInfo")
    async def extract_document_info(
        self, 
        text: str, 
        critic_feedback: Optional[Dict[str, Any]] = None,
        is_structured_markdown: bool = False,
        planner_instruction: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract structured information from document text using LLM.
        Self-adapts based on document content and critic feedback.
        
        Args:
            text: Document text content
            critic_feedback: Optional feedback from Critic agent for improvement
            is_structured_markdown: If True, text is MinerU-converted Markdown with better structure
            
        Returns:
            Dictionary containing extracted information
        """
        # Use generous context window for modern LLMs (200K+ token support)
        # Get limits from config (adjustable based on your LLM capabilities)
        max_length = (
            config.max_doc_context_markdown if is_structured_markdown 
            else config.max_doc_context_text
        )
        
        original_length = len(text)
        if original_length > max_length:
            # Smart truncation for scientific papers: try to exclude References section
            # Look for common reference section markers
            import re
            ref_patterns = [
                r'\n#+\s*References?\s*\n',  # Markdown headers: # References, ## Reference
                r'\n\*\*References?\*\*\s*\n',  # Bold: **References**
                r'\nReferences?\s*\n',  # Plain: References
                r'\nBIBLIOGRAPHY\s*\n',
                r'\nCitations?\s*\n'
            ]
            
            ref_start_pos = None
            for pattern in ref_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    ref_start_pos = match.start()
                    logger.info(f"Detected References section at position {ref_start_pos:,}")
                    break
            
            # If we found references and they start beyond our max_length, just truncate before them
            if ref_start_pos and ref_start_pos < original_length * 0.9:  # References in last 10%
                # Try to keep content before references
                if ref_start_pos <= max_length:
                    # References start within our limit - keep everything before references
                    text = text[:ref_start_pos] + "\n\n[... References section truncated ...]"
                    logger.warning(
                        f"Document truncated at References section: {original_length:,} chars -> {ref_start_pos:,} chars"
                    )
                else:
                    # References start beyond our limit - use start/end strategy but stop before refs
                    keep_start = int(max_length * 0.95)  # 95% from start
                    keep_end = min(int(max_length * 0.05), ref_start_pos - keep_start)  # 5% from end, but before refs
                    if keep_end > 0 and keep_start + keep_end < ref_start_pos:
                        truncated_chars = ref_start_pos - keep_start - keep_end
                        text = (
                            text[:keep_start] + 
                            f"\n\n[... middle section truncated ({truncated_chars:,} characters) ...]\n\n" +
                            text[ref_start_pos - keep_end:ref_start_pos] +
                            "\n\n[... References section truncated ...]"
                        )
                        logger.warning(
                            f"Document truncated: {original_length:,} chars -> ~{max_length:,} chars "
                            f"(kept {keep_start:,} start + {keep_end:,} pre-references, removed middle + references)"
                        )
                    else:
                        # Fallback: just take from start up to limit
                        text = text[:max_length] + "\n\n[... remainder including References truncated ...]"
                        logger.warning(f"Document truncated: {original_length:,} chars -> {max_length:,} chars (simple cut)")
            else:
                # No references found or they're very early - use smart start-heavy strategy
                # For scientific papers, prioritize beginning (abstract, methods, results)
                keep_start = int(max_length * 0.95)  # 95% from start
                keep_end = int(max_length * 0.05)    # 5% from end
                truncated_chars = original_length - keep_start - keep_end
                
                text = (
                    text[:keep_start] + 
                    f"\n\n[... end section truncated ({truncated_chars:,} characters) ...]\n\n" +
                    text[-keep_end:]
                )
                logger.warning(
                    f"Document truncated: {original_length:,} chars -> {max_length:,} chars "
                    f"(kept {keep_start:,} start + {keep_end:,} end)"
                )
        
        # Build adaptive system prompt based on input format
        if is_structured_markdown:
            system_prompt = """You are an expert at extracting ESSENTIAL structured metadata from research-related documents.

**CRITICAL CONSTRAINTS - READ FIRST:**
1. Maximum response size: 20,000 characters (~5,000 tokens)
2. Extract ONLY key structured metadata - DO NOT include full text or detailed explanations
3. Each field value: concise (< 300 characters unless specifically needed)
4. If document is long, extract SUMMARY information, not everything
5. Prioritize essential information over completeness

**Document Format:** This document has been professionally converted to Markdown with preserved structure, tables, and image references. Leverage this enhanced structure for precise extraction.

**IMPORTANT - Document Type Flexibility:**
This could be ANY type of research document:
- Research papers, preprints, technical reports
- Project proposals, grant applications (e.g., Horizon Europe, NSF)
- Data management plans (DMP)
- Protocol documents, standard operating procedures (SOP)
- Meeting minutes, workshop reports
- Datasets documentation, README files
- Institutional reports, white papers

**Your task:** 
1. FIRST identify what type of document this is
2. THEN extract ONLY the ESSENTIAL metadata appropriate for that document type
3. DO NOT force a paper structure (title/abstract/authors) if it doesn't fit
4. Adapt your extraction strategy to the actual content

**DO Extract:**
- Key identifiers (titles, IDs, names, DOIs)
- Structured data (dates, numbers, categories)
- Relationships (authors, affiliations, organizations)
- Critical context (1-2 sentence summaries, not full paragraphs)

**DO NOT Extract:**
- Full paragraphs or text sections
- Detailed explanations or background
- Complete literature reviews
- Methodology details beyond key parameters
- Full result descriptions (only key findings)

**Core principles:**
1. Use headers to understand document structure and content organization
2. Parse tables directly to extract structured data (budgets, timelines, parameters, etc.)
3. Identify figure captions and their context from image references
4. Extract list items (partners, work packages, deliverables, methods, etc.)
5. Use clear, descriptive field names that match the actual content
6. Create hierarchical structures where appropriate

**Adapt extraction to document type:**

For **Project Proposals/Grants**:
- Project info: acronym, title, funding program, duration, budget
- Consortium: partners, roles, expertise, infrastructure
- Objectives: goals, work packages, deliverables, milestones
- Methodology: approach, innovation, expected impact
- Management: coordination, ethics, data management plan

For **Research Papers**:
- Bibliographic: title, authors, affiliations, DOI, journal
- Research: domain, objectives, hypotheses, methodology
- Data: samples, measurements, instruments, datasets
- Results: findings, statistics, conclusions

For **Data Management Plans**:
- Data types, formats, volumes, repositories
- Access policies, licenses, preservation strategy
- Metadata standards, quality assurance
- Responsibilities, resources, timeline

For **Protocols/SOPs**:
- Purpose, scope, materials, equipment
- Step-by-step procedures, parameters, controls
- Safety considerations, quality checks
- References, version history

**Output format:**
Return a comprehensive JSON object with field names that reflect the ACTUAL content.
DO NOT use generic "title/abstract/authors" if the document doesn't have them.

Example for a project proposal:
```json
{
  "document_type": "project_proposal",
  "project_acronym": "...",
  "funding_programme": "...",
  "consortium": [...],
  "objectives": [...],
  "work_packages": [...],
  "budget": {...}
}
```

Example for a research paper:
```json
{
  "document_type": "research_paper",
  "title": "...",
  "authors": [...],
  "methodology": {...},
  "results": {...}
}
```

**Best practices:**
- Extract numerical data with units preserved
- Capture hierarchical relationships naturally present in the document
- Include both human-readable descriptions AND structured identifiers (PICs, DOIs, ORCIDs, etc.)
- When tables are present, extract their full content as structured data
- Preserve scientific notation, formulas, and technical terminology
- Use descriptive field names that make sense for the content

**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix and ``` suffix.
Format your response EXACTLY like this:
```json
{
  "your": "json content here"
}
```

REQUIREMENTS:
- ALWAYS start with ```json on its own line
- ALWAYS end with ``` on its own line
- DO NOT include any explanatory text before or after the code block
- DO NOT include comments or notes inside the JSON
- Return ONLY the markdown code block with JSON content, nothing else."""
        else:
            system_prompt = """You are an expert at extracting ESSENTIAL structured metadata from research-related documents.

**CRITICAL CONSTRAINTS - READ FIRST:**
1. Maximum response size: 20,000 characters (~5,000 tokens)
2. Extract ONLY key structured metadata - DO NOT include full text or detailed explanations
3. Each field value: concise (< 300 characters unless specifically needed)
4. If document is long, extract SUMMARY information, not everything
5. Prioritize essential information over completeness

**CRITICAL - Document Type Flexibility:**
This could be ANY type of research document:
- Research papers, preprints, technical reports
- Project proposals, grant applications (Horizon Europe, NSF, etc.)
- Data management plans (DMP)
- Protocol documents, SOPs
- Meeting reports, workshop summaries
- Dataset documentation, README files
- Institutional reports, white papers

**Your task:** 
1. FIRST identify what type of document this is
2. THEN extract ONLY the ESSENTIAL metadata appropriate for that document type
3. DO NOT force a paper structure (title/abstract/authors) if it doesn't fit
4. Adapt your extraction strategy to the actual content
5. Be CONCISE - extract structured metadata, not full text

**Core principles:**
1. Understand the document type and purpose
2. Identify what ESSENTIAL information is actually present and relevant
3. Use clear, descriptive field names that match the content
4. Create hierarchical structures where appropriate
5. Be flexible - different documents need different extraction strategies
6. Prioritize brevity - use summaries and key facts, not full descriptions

**Adapt extraction to document type:**

For **Project Proposals/Grants**: Extract project info, consortium, objectives, work packages, budget, management, ethics, data plans

For **Research Papers**: Extract bibliographic info, research context, methodology, data, results, conclusions

For **Data Management Plans**: Extract data types, repositories, access policies, metadata standards, responsibilities

For **Protocols/SOPs**: Extract purpose, materials, procedures, parameters, safety, quality controls

**DO Extract:**
- Key identifiers (titles, IDs, names, DOIs, ORCIDs, PICs)
- Structured data (dates, numbers, categories, classifications)
- Relationships (authors, affiliations, organizations, partners)
- Critical context (1-2 sentence summaries, not full paragraphs)
- Essential parameters (with units)

**DO NOT Extract:**
- Full paragraphs or complete text sections
- Detailed explanations or extensive background
- Complete literature reviews or citations
- Full methodology descriptions (only key parameters and methods)
- Complete result descriptions (only key findings/conclusions)

**Output format:**
Return a JSON object with field names that reflect the ACTUAL content.
DO NOT use generic "title/abstract/authors" if the document doesn't have them.
Use descriptive, specific field names (e.g., "project_acronym", "funding_programme", "consortium", "work_packages" for proposals).

**Best practices:**
- Include a "document_type" field to indicate what kind of document this is
- Keep values concise - use summaries, not full text
- Extract numerical data with units preserved
- Capture hierarchical relationships naturally present in the document
- Include both human-readable descriptions AND structured identifiers
- Use descriptive field names that make sense for the content

**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix and ``` suffix.
Format your response EXACTLY like this:
```json
{
  "your": "json content here"
}
```

REQUIREMENTS:
- ALWAYS start with ```json on its own line
- ALWAYS end with ``` on its own line
- DO NOT include any explanatory text before or after the code block
- DO NOT include comments or notes inside the JSON
- Return ONLY the markdown code block with JSON content, nothing else."""

        # Add critic feedback if available
        if critic_feedback:
            feedback_text = f"\n\n**Previous attempt feedback:**\n"
            for issue in critic_feedback.get('issues', []):
                feedback_text += f"- Issue: {issue}\n"
            for suggestion in critic_feedback.get('suggestions', []):
                feedback_text += f"- Suggestion: {suggestion}\n"
            system_prompt += feedback_text
        
        if planner_instruction:
            system_prompt += f"\n\n**Planner guidance:**\n- {planner_instruction}\n"

        if is_structured_markdown:
            user_prompt = f"""Analyze this Markdown-formatted research document and extract comprehensive metadata:

{text}

**Extraction Strategy:**
1. Identify document type and scientific domain from headers and content
2. Parse structured elements:
   - Use # headers to locate sections (Title, Abstract, Methods, Results, Discussion)
   - Extract data from tables (experimental design, measurements, parameters)
   - Identify figure/image references and their captions
   - Parse lists (authors, affiliations, materials, protocols)
3. Extract domain-specific metadata:
   - Study design: subjects, treatments, controls, replicates
   - Measurements: variables, units, instruments, methods
   - Spatial/temporal: locations, coordinates, dates, duration
   - Data: repositories, accessions, file formats
4. Capture relationships and hierarchy (study→experiments→samples→measurements)
5. Ensure FAIR compliance: include identifiers, controlled vocabularies, provenance

Return comprehensive JSON with hierarchical structure and descriptive field names."""
        else:
            user_prompt = f"""Analyze and extract information from this research document:

{text}

Think step by step:
1. What type of document is this? (research paper, dataset description, protocol, etc.)
2. What scientific domain does it belong to?
3. What key information does it contain?
4. What metadata would be most valuable for FAIR data principles?

Extract all relevant information and return as JSON with clear, descriptive field names."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Extract Document Info")
            content = getattr(response, 'content', None) if response else None
            
            # Check if response is empty
            if not content or len(str(content).strip()) == 0:
                error_msg = f"LLM returned empty response. Provider: {self.provider}, Model: {self.model}"
                logger.error(f"❌ {error_msg}")
                logger.error(f"Response object: {response}")
                logger.error(f"Response type: {type(response)}")
                raise ValueError(error_msg)
            
            # Note: LLM response is automatically logged by _call_llm
            
            # Parse JSON response using improved parser
            logger.debug(f"Attempting to parse LLM response ({len(content)} chars)")
            logger.debug(f"Response starts with: {content[:100]}")
            logger.debug(f"Response ends with: {content[-100:]}")
            
            doc_info = _parse_json_with_fallback(content)
            
            if doc_info:
                logger.info(f"✅ Extracted document info with {len(doc_info)} fields")
                return doc_info
            else:
                # All parsing strategies failed - this is a critical error
                logger.error(f"❌ Failed to parse LLM response as JSON after all fallback strategies")
                logger.error(f"Response content (first 2000 chars): {content[:2000]}")
                logger.error(f"Response length: {len(content)} chars")
                logger.error(f"Has ```json: {'```json' in content}")
                logger.error(f"Has backticks: {'```' in content}")
                
                # Raise error to trigger retry mechanism
                raise ValueError(f"Failed to parse LLM response as JSON. Response length: {len(content)} chars")
        except Exception as e:
            logger.error(f"Error during document info extraction: {e}")
            raise  # Re-raise to trigger retry
    
    @traceable(name="LLM.GenerateMetadataValue")
    async def generate_metadata_value(
        self,
        field_name: str,
        field_description: str,
        document_info: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a value for a metadata field based on document info.
        
        Args:
            field_name: Name of the metadata field
            field_description: Description of what the field should contain
            document_info: Extracted document information
            context: Additional context (retrieved knowledge, etc.)
            
        Returns:
            Dict with 'value', 'evidence', and 'confidence'
        """
        system_prompt = """You are an expert at generating FAIR metadata values from research documents.
Given a field description and document information, generate an appropriate value.

**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix and ``` suffix.
Format your response EXACTLY like this:
```json
{
  "value": "generated value",
  "evidence": "explanation",
  "confidence": 0.95
}
```

REQUIREMENTS:
- ALWAYS start with ```json on its own line
- ALWAYS end with ``` on its own line
- DO NOT include any explanatory text before or after the code block
- DO NOT include comments or notes inside the JSON
- Return ONLY the markdown code block with JSON content, nothing else."""

        user_prompt = f"""Generate a value for this metadata field:

Field: {field_name}
Description: {field_description}

Document Information:
{json.dumps(document_info, indent=2)}

{"Context: " + json.dumps(context, indent=2) if context else ""}

Return JSON with value, evidence, and confidence."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Generate Metadata Value")
            content = getattr(response, 'content', None) if response else None
            
            # Check if response is empty
            if not content or len(str(content).strip()) == 0:
                error_msg = f"LLM returned empty response. Provider: {self.provider}, Model: {self.model}"
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            # Note: LLM response is automatically logged by _call_llm
            
            # Parse JSON
            content = _extract_json_from_markdown(content)
            
            result = json.loads(content)
            
            # Ensure required fields
            if "value" not in result:
                result["value"] = ""
            if "evidence" not in result:
                result["evidence"] = f"Generated from {field_name}"
            if "confidence" not in result:
                result["confidence"] = 0.5
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating metadata value for {field_name}: {e}")
            return {
                "value": "",
                "evidence": f"Error: {str(e)}",
                "confidence": 0.0
            }
    
    @traceable(name="LLM.SelectRelevantFields")
    async def select_relevant_metadata_fields(
        self,
        document_info: Dict[str, Any],
        available_fields: List[Dict[str, Any]],
        critic_feedback: Optional[Dict[str, Any]] = None,
        planner_instruction: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Intelligently select relevant metadata fields based on document content.
        Adapts based on critic feedback.
        
        Args:
            document_info: Extracted document information
            available_fields: All available metadata fields from FAIR-DS
            critic_feedback: Optional feedback for improvement
            
        Returns:
            List of selected field dictionaries with rationale
        """
        # Use complete document_info instead of extracting specific fields
        # This is more flexible and works with any document type
        doc_summary = document_info
        
        # Group fields by ISA sheet to ensure balanced selection across ISA levels
        isa_sheets = ["investigation", "study", "assay", "sample", "observationunit"]
        fields_by_isa = {sheet: [] for sheet in isa_sheets}
        
        for field in available_fields:
            isa_sheet = field.get("isa_sheet", "study")
            if isa_sheet in fields_by_isa:
                fields_by_isa[isa_sheet].append(field)
            else:
                # Fallback to study if unknown
                fields_by_isa["study"].append(field)
        
        # Prepare available fields summary, grouped by ISA sheet
        fields_summary_by_isa = {}
        for sheet in isa_sheets:
            fields_summary_by_isa[sheet] = []
            # Show ALL fields for each ISA sheet (no truncation)
            for field in fields_by_isa[sheet]:
                fields_summary_by_isa[sheet].append({
                    "name": field.get("name", ""),
                    "description": field.get("description", "")[:200],  # Increased limit
                    "package": field.get("metadata", {}).get("package", ""),
                    "required": field.get("required", False)
                })
        
        # Count fields per ISA sheet
        field_counts = {sheet: len(fields_by_isa[sheet]) for sheet in isa_sheets}
        
        system_prompt = """You are an expert at selecting appropriate metadata fields for scientific research data.

**Your task:** Analyze the document and intelligently select the MOST RELEVANT metadata fields from the available options, ensuring balanced coverage across ISA hierarchy levels.

**ISA Hierarchy:**
- **Investigation**: Project/investigation-level metadata (e.g., investigation title, description, investigators)
- **Study**: Study-level metadata (e.g., study title, description, experimental design)
- **Assay**: Assay-level metadata (e.g., assay type, protocol, measurement technology)
- **Sample**: Sample-level metadata (e.g., sample description, collection method, biological material)
- **ObservationUnit**: ObservationUnit-level metadata (e.g., sampling sites, environmental context)

**Principles:**
1. Match fields to actual document content - don't select fields for information that isn't present
2. Prioritize fields that capture the core information of this specific study
3. Consider the research domain and adapt field selection accordingly
4. Include both core bibliographic fields and domain-specific fields
5. **IMPORTANT**: Ensure balanced selection across ISA hierarchy levels - select fields from multiple ISA sheets, not just one
6. Select 20-30 fields total - enough for comprehensive metadata but not overwhelming

**Selection criteria:**
- Relevance to the document's content and domain
- Availability of information in the document
- FAIR principles - findability, accessibility, interoperability, reusability
- Balance between general and specific fields
- **Balance across ISA hierarchy levels** - don't focus only on one ISA sheet

**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix and ``` suffix.
Format your response EXACTLY like this:
```json
{
  "selected_fields": [
    {"field_name": "...", "reason": "why this field is relevant"}
  ],
  "rationale": "overall selection strategy, including ISA level balance"
}
```

REQUIREMENTS:
- ALWAYS start with ```json on its own line
- ALWAYS end with ``` on its own line
- DO NOT include any explanatory text before or after the code block
- DO NOT include comments or notes inside the JSON
- Return ONLY the markdown code block with JSON content, nothing else."""

        if critic_feedback:
            feedback_text = f"\n\n**Improve based on feedback:**\n"
            for issue in critic_feedback.get('issues', []):
                feedback_text += f"- {issue}\n"
            for suggestion in critic_feedback.get('suggestions', []):
                feedback_text += f"- {suggestion}\n"
            system_prompt += feedback_text
        
        if planner_instruction:
            system_prompt += f"\n\n**Planner guidance:**\n- {planner_instruction}\n"

        user_prompt = f"""Complete document information:
{json.dumps(doc_summary, indent=2, ensure_ascii=False)}

Available metadata fields by ISA sheet:
{json.dumps(fields_summary_by_isa, indent=2)}

Field counts per ISA sheet:
{json.dumps(field_counts, indent=2)}

**IMPORTANT**: Select fields from MULTIPLE ISA sheets to ensure balanced coverage. Don't focus only on one ISA level.

Select the most appropriate 20-30 metadata fields for this document, ensuring representation across ISA hierarchy levels.

**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix and ``` suffix.
Format your response EXACTLY like this:
```json
{
  "your": "json content here"
}
```

REQUIREMENTS:
- ALWAYS start with ```json on its own line
- ALWAYS end with ``` on its own line
- DO NOT include any explanatory text before or after the code block
- DO NOT include comments or notes inside the JSON
- Return ONLY the markdown code block with JSON content, nothing else."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Select Relevant Fields")
            content = getattr(response, 'content', None) if response else None
            
            # Check if response is empty
            if not content or len(str(content).strip()) == 0:
                error_msg = f"LLM returned empty response. Provider: {self.provider}, Model: {self.model}"
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            # Note: LLM response is automatically logged by _call_llm
            
            content = _extract_json_from_markdown(content)
            result = json.loads(content)
            selected = result.get("selected_fields", [])
            
            # Match selected field names back to full field objects
            selected_field_names = {f["field_name"] for f in selected}
            matched_fields = [f for f in available_fields if f.get("name") in selected_field_names]
            
            logger.info(f"Selected {len(matched_fields)} relevant fields out of {len(available_fields)}")
            return matched_fields
            
        except Exception as e:
            logger.error(f"Error selecting relevant fields: {e}")
            raise  # Re-raise to trigger retry mechanism
    
    @traceable(name="LLM.GenerateMetadataJSON")
    async def generate_complete_metadata(
        self,
        document_info: Dict[str, Any],
        selected_fields: List[Dict[str, Any]],
        document_text: str,
        critic_feedback: Optional[Dict[str, Any]] = None,
        planner_instruction: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate complete metadata for all selected fields.
        Adapts based on document content and critic feedback.
        
        Args:
            document_info: Extracted document information
            selected_fields: Selected metadata fields
            document_text: Full document text (truncated)
            critic_feedback: Optional feedback for improvement
            
        Returns:
            List of metadata field dictionaries with values
        """
        # Truncate document text
        if len(document_text) > 6000:
            document_text = document_text[:6000] + "\n[... truncated ...]"
        
        system_prompt = """You are an expert at generating FAIR metadata from research documents.

**CRITICAL CONSTRAINTS - READ FIRST:**
1. Maximum response size: 50,000 characters (~12,000 tokens)
2. Each field value: concise (< 500 characters)
3. Each evidence: brief (< 200 characters)
4. Use summaries, not full quotes or paragraphs

**Your task:** For EACH AND EVERY metadata field in the list, extract or generate an appropriate value from the document.

**CRITICAL REQUIREMENTS:**
1. **MUST generate a value for ALL fields** - You must return a value for every single field in the provided list, no exceptions
2. **Investigation-level fields** - Project-level metadata. Extract from title/abstract or derive from context
3. **Study-level fields** - Study description. Extract from title/abstract/methods/results
4. **Assay-level fields** - Measurement methods. Extract from methods
5. **Sample-level fields** - Biological material. Extract from methods/results
6. **ObservationUnit-level fields** - Sampling sites. Extract from methods/environmental context

**Principles:**
1. Extract values directly from document when possible - keep concise
2. Generate appropriate values when information is implicit
3. Provide brief evidence (not full quotes)
4. Assign realistic confidence scores (0.0-1.0)
5. If information truly isn't available, use "not specified" but STILL include the field

**For each field, provide:**
- field_name: MUST match exactly one of the field names in the provided list
- value: Concise metadata value (< 500 chars) - use summaries, not full text
- evidence: Brief source location (< 200 chars) - e.g., "Methods section" not full quote
- confidence: Float 0.0-1.0 (1.0 = explicit, 0.7-0.9 = strong inference, 0.4-0.6 = reasonable inference, 0.0-0.3 = not available)

**IMPORTANT:** 
- You MUST return a JSON array with exactly the same number of fields as provided in the input list
- Do NOT skip any fields, even if information is limited
- For investigation/study fields: If not explicitly stated, derive from document title/abstract
- For fields with limited information, use "not specified" but still include the field
- Keep all values concise (< 500 chars each)
- Keep all evidence brief (< 200 chars each)

**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**
Wrap your JSON array in markdown code blocks EXACTLY like this:

```json
[
  {{
    "field_name": "...",
    "value": "concise value",
    "evidence": "brief source",
    "confidence": 0.X
  }}
]
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON array only
- Line N+1: ``` (alone)
- NO text before the opening ```json
- NO text after the closing ```
- NO comments in JSON
- Each value: < 500 characters
- Each evidence: < 200 characters"""

        if critic_feedback:
            feedback_text = f"\n\n**Address these issues:**\n"
            for issue in critic_feedback.get('issues', []):
                feedback_text += f"- {issue}\n"
            for suggestion in critic_feedback.get('suggestions', []):
                feedback_text += f"- {suggestion}\n"
            system_prompt += feedback_text
        
        if planner_instruction:
            system_prompt += f"\n\n**Planner guidance:**\n- {planner_instruction}\n"

        # Prepare field descriptions
        field_descriptions = []
        for field in selected_fields:
            field_descriptions.append({
                "field_name": field.get("name", ""),  # Use exact field name from FAIR-DS
                "description": field.get("description", ""),
                "required": field.get("required", False)
            })

        # Group fields by ISA sheet for better context
        isa_sheets = ["investigation", "study", "assay", "sample", "observationunit"]
        fields_by_isa = {sheet: [] for sheet in isa_sheets}
        for field in selected_fields:
            isa_sheet = field.get("isa_sheet", "study")
            if isa_sheet in fields_by_isa:
                fields_by_isa[isa_sheet].append(field)
            else:
                fields_by_isa["study"].append(field)
        
        # Count fields per ISA sheet
        field_counts = {sheet: len(fields_by_isa[sheet]) for sheet in isa_sheets}
        
        user_prompt = f"""Document information:
{json.dumps(document_info, indent=2, ensure_ascii=False)}

Document excerpt:
{document_text[:3000]}

Metadata fields to populate (TOTAL: {len(selected_fields)} fields):
{json.dumps(field_descriptions, indent=2)}

Fields by ISA hierarchy:
{json.dumps(field_counts, indent=2)}

**CRITICAL REQUIREMENTS:**
1. You MUST return a JSON array with EXACTLY {len(selected_fields)} fields - one for each field in the list above
2. Use the EXACT field_name from the list above. Do not modify or abbreviate field names
3. **DO NOT DUPLICATE field_name values** - each field_name must appear exactly once in your response
4. **Investigation-level fields** ({field_counts.get('investigation', 0)} fields): Must generate values from document title, abstract, or research context
5. **Study-level fields** ({field_counts.get('study', 0)} fields): Must generate values from document title, abstract, methods, or results
6. **Assay-level fields** ({field_counts.get('assay', 0)} fields): Must generate values from methods section
7. **Sample-level fields** ({field_counts.get('sample', 0)} fields): Must generate values from methods or results
8. **ObservationUnit-level fields** ({field_counts.get('observationunit', 0)} fields): Must generate values from methods or environmental context

**For fields where information is not explicitly stated:**
- Investigation/Study fields: Derive from document title/abstract
- Other fields: Use "not specified" but STILL include the field

**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**
Wrap your JSON array in markdown code blocks:

```json
[
  {{
    "field_name": "exact_name",
    "value": "concise value < 500 chars",
    "evidence": "brief source < 200 chars",
    "confidence": 0.X
  }}
]
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON array with EXACTLY {len(selected_fields)} fields
- Line N+1: ``` (alone)
- NO text before/after block
- NO comments in JSON
- Each value: < 500 characters
- Each evidence: < 200 characters"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Generate Complete Metadata")
            content = getattr(response, 'content', None) if response else None
            
            # Check if response is empty
            if not content or len(str(content).strip()) == 0:
                error_msg = f"LLM returned empty response. Provider: {self.provider}, Model: {self.model}"
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            # Note: LLM response is automatically logged by _call_llm
            
            if not content or not content.strip():
                logger.warning("LLM returned empty response for generate_complete_metadata")
                return [
                    {
                        "field_name": f.get("name", ""),
                        "value": "",
                        "evidence": "LLM returned empty response",
                        "confidence": 0.0
                    }
                    for f in selected_fields[:10]
                ]
            
            content = _extract_json_from_markdown(content)
            metadata = json.loads(content)
            
            logger.info(f"Generated metadata for {len(metadata)} fields")
            return metadata if isinstance(metadata, list) else [metadata]
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response content: {content[:500]}")
            raise ValueError(f"JSON parsing error: {e}")  # Trigger retry
        except Exception as e:
            logger.error(f"Error generating metadata: {e}")
            raise  # Re-raise to trigger retry mechanism
    
    @traceable(name="LLM.EvaluateQuality")
    async def evaluate_quality(
        self,
        content: str,
        criteria: List[str],
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate quality of content against criteria.
        
        Args:
            content: Content to evaluate
            criteria: List of quality criteria
            context: Additional context for evaluation
            
        Returns:
            Dict with evaluation results (always includes issues and suggestions)
        """
        # Get thresholds from config
        accept_threshold = config.critic_accept_threshold_general
        retry_min = config.critic_retry_min_threshold
        retry_max = config.critic_retry_max_threshold
        
        system_prompt = f"""You are an expert quality evaluator for scientific metadata extraction.
Evaluate the provided content against the given criteria.

**Evaluation Principles:**
1. Assess what IS present, not what is missing - focus on the quality of extracted information
2. Be realistic - if information is not in the source document, don't penalize heavily
3. Consider the extraction quality: Are extracted fields accurate and complete based on available source?
4. Distinguish between:
   - Missing information that was never in the source (minor issue)
   - Incorrect or incomplete extraction from available source (major issue)
   - Poor quality or truncated values (major issue)

**Scoring Guidelines:**
- overall_score: 0.8-1.0 = Excellent extraction quality, all available information captured well
- overall_score: 0.6-0.79 = Good extraction, minor gaps or issues
- overall_score: 0.4-0.59 = Acceptable but needs improvement
- overall_score: 0.0-0.39 = Poor quality, significant issues

**Decision Guidelines:**
- ACCEPT: overall_score >= {accept_threshold} AND extraction quality is good (even if some info missing from source)
- RETRY: overall_score {retry_min}-{retry_max} OR extraction quality can be improved
- ESCALATE: overall_score < {retry_min} OR critical errors in extraction

Return JSON with:
- overall_score: Float 0-1 (based on extraction quality, not completeness of source)
- passed_criteria: List of criteria that passed
- failed_criteria: List of criteria that failed
- issues: List of specific issues found (empty list if none)
- suggestions: List of specific improvement suggestions (empty list if none)
- decision: "ACCEPT", "RETRY", or "ESCALATE"

IMPORTANT: Always include 'issues' and 'suggestions' as arrays (can be empty).

**OUTPUT FORMAT - CRITICAL:**
You MUST wrap your JSON response in markdown code blocks with ```json prefix and ``` suffix.
Format your response EXACTLY like this:
```json
{
  "your": "json content here"
}
```

REQUIREMENTS:
- ALWAYS start with ```json on its own line
- ALWAYS end with ``` on its own line
- DO NOT include any explanatory text before or after the code block
- DO NOT include comments or notes inside the JSON
- Return ONLY the markdown code block with JSON content, nothing else."""

        criteria_text = "\n".join(f"- {c}" for c in criteria)
        
        user_prompt = f"""Evaluate this extracted content:

{content}

Criteria to evaluate:
{criteria_text}

{f"Context: {context}" if context else ""}

**Important:** Evaluate the QUALITY of extraction, not whether the source document contains all ideal information.
- If information is missing because it's not in the source document, note it but don't heavily penalize
- If information is incorrectly extracted or truncated, this is a quality issue
- Focus on: Are the extracted fields accurate, complete, and well-structured based on what was available?

Provide detailed evaluation as JSON with issues and suggestions arrays."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Evaluate Quality")
            response_content = getattr(response, 'content', None)
            
            # Note: LLM response is automatically logged by _call_llm
            
            # Check if response is empty
            if not response_content or not response_content.strip():
                logger.warning("LLM returned empty response for evaluate_quality, using default")
                return {
                    "overall_score": 0.5,
                    "passed_criteria": [],
                    "failed_criteria": criteria,
                    "issues": ["LLM returned empty response"],
                    "suggestions": ["Retry evaluation"],
                    "decision": "RETRY"
                }
        except Exception as e:
            logger.error(f"Error during LLM evaluation: {e}")
            return {
                "overall_score": 0.3,
                "passed_criteria": [],
                "failed_criteria": criteria,
                "issues": [f"LLM call failed: {str(e)}"],
                "suggestions": ["LLM service error, retry needed"],
                "decision": "RETRY"
            }
        
        # Parse JSON using improved parser
        result = _parse_json_with_fallback(response_content)
        
        if not result:
            logger.error(f"Failed to parse LLM response as JSON after all fallback strategies")
            logger.error(f"Response content: {response_content[:500]}")
            # Return default structure
            return {
                "overall_score": 0.5,
                "passed_criteria": [],
                "failed_criteria": criteria,
                "issues": ["JSON parsing error: all fallback strategies failed"],
                "suggestions": ["LLM response format invalid, retry needed"],
                "decision": "RETRY"
            }
        
        # Ensure required fields always exist
        if "issues" not in result:
            result["issues"] = result.get("failed_criteria", [])
        if "suggestions" not in result:
            result["suggestions"] = []
        if "decision" not in result:
            result["decision"] = "ACCEPT"
        if "overall_score" not in result:
            result["overall_score"] = 0.5
        
        return result


# Global instance
_llm_helper = None
_last_provider = None
_last_model = None
_last_base_url = None


def check_ollama_model_available(base_url: str, model_name: str, timeout: int = 5) -> tuple[bool, str]:
    """
    Verify that the requested Ollama model exists on the server.

    Uses GET /api/tags to list models; checks for exact match or tag suffix match
    (e.g. "phi4" matches "phi4:latest", "phi4:7b").

    Returns:
        (True, resolved_name) if model is available, e.g. (True, "phi4:latest").
        (False, error_message) if not available or request failed.
    """
    if not base_url or not model_name:
        return False, "base_url and model_name are required"
    try:
        import requests
    except ImportError:
        return False, "requests not installed; cannot verify Ollama model"
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return False, f"Ollama returned HTTP {r.status_code}"
        data = r.json()
        models = data.get("models") or []
        names = [m.get("name") for m in models if isinstance(m, dict) and m.get("name")]
        # Exact match
        if model_name in names:
            return True, model_name
        # Match without tag: "phi4" matches "phi4:latest", "phi4:7b"
        model_lower = model_name.lower()
        for name in names:
            if name.lower() == model_lower or name.lower().startswith(model_lower + ":"):
                return True, name
        available = ", ".join(names[:15]) if names else "none"
        if len(names) > 15:
            available += f", ... ({len(names)} total)"
        return False, (
            f"model '{model_name}' not found on Ollama server. "
            f"Available: {available}. "
            f"Pull with: ollama pull {model_name}"
        )
    except requests.exceptions.RequestException as e:
        return False, f"Ollama unreachable: {e}"
    except (ValueError, KeyError) as e:
        return False, f"Invalid response from Ollama: {e}"


def get_llm_helper(force_reinit=False) -> LLMHelper:
    """Get or create the global LLM helper instance.
    
    Args:
        force_reinit: If True, force reinitialization even if instance exists.
                     This is useful when configuration has changed.
    """
    global _llm_helper, _last_provider, _last_model, _last_base_url
    
    # Check if we need to reinitialize due to config changes
    current_provider = config.llm_provider
    current_model = config.llm_model
    current_base_url = config.llm_base_url
    
    needs_reinit = (
        force_reinit or
        _llm_helper is None or
        _last_provider != current_provider or
        _last_model != current_model or
        _last_base_url != current_base_url
    )
    
    if needs_reinit:
        _llm_helper = LLMHelper()
        _last_provider = current_provider
        _last_model = current_model
        _last_base_url = current_base_url
        logger.info(f"🔄 Reinitialized LLMHelper: provider={current_provider}, model={current_model}, base_url={current_base_url}")
    
    return _llm_helper


def reset_llm_helper():
    """Reset the global LLM helper instance (force reinitialization on next call)."""
    global _llm_helper, _last_provider, _last_model, _last_base_url
    _llm_helper = None
    _last_provider = None
    _last_model = None
    _last_base_url = None


def save_llm_responses(output_path: Path, llm_helper: Optional[LLMHelper] = None):
    """Save LLM responses to file for debugging."""
    if llm_helper is None:
        llm_helper = get_llm_helper()
    
    responses_file = output_path / "llm_responses.json"
    with open(responses_file, 'w', encoding='utf-8') as f:
        json.dump(llm_helper.llm_responses, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved {len(llm_helper.llm_responses)} LLM responses to {responses_file}")

