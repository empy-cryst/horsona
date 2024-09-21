import json
from typing import Type
from xml.sax.saxutils import escape as xml_escape

from pydantic import BaseModel


def _convert_to_xml(obj, prefix, indent):
    """
    Serialize an object to a JSON string.

    This function first normalizes the object using _normalize(),
    then serializes it to a JSON string with indentation.

    Args:
        obj: The object to serialize.

    Returns:
        str: The JSON string representation of the object.
    """
    if isinstance(obj, dict):
        result = []
        for key, value in obj.items():
            value_str = _convert_to_xml(value, f"{prefix}.{key}", indent + 1)
            result.append(f'\n{"  " * indent}<{key}>{value_str}</{key}>')
        return "".join(result) + "\n"
    elif isinstance(obj, list):
        result = []
        for i, value in enumerate(obj):
            value_str = _convert_to_xml(value, prefix, indent + 1)
            result.append(
                f'\n{"  " * indent}<{prefix}.{i}>{value_str}{"  " * indent}</{prefix}.{i}>'
            )
        return "".join(result) + "\n"
    else:
        return f"{xml_escape(str(obj))}"


async def compile_user_prompt(**kwargs):
    """
    Compile a user prompt from keyword arguments.

    Each keyword argument is serialized and wrapped in XML-like tags.

    Args:
        **kwargs: Keyword arguments to include in the prompt.

    Returns:
        str: The compiled user prompt.
    """
    prompt_pieces = []
    for key, value in kwargs.items():
        value = _convert_to_xml(await _convert_to_dict(value), key, 1)
        prompt_pieces.append(f"<{key}>{value}</{key}>")

    return "\n\n".join(prompt_pieces)


def _compile_obj_system_prompt(response_model: Type[BaseModel]):
    """
    Compile a system prompt for a given response model.

    This function creates a prompt instructing the model to return
    a JSON object matching the schema of the provided response model.

    Args:
        response_model (BaseModel): The Pydantic model to use for the response schema.

    Returns:
        str: The compiled system prompt.
    """
    schema = response_model.model_json_schema()
    return (
        "Your task is to understand the content and provide "
        "the parsed objects in json that matches the following json_schema:\n\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Make sure to return an instance of the JSON, not the schema itself."
    )


async def generate_obj_query_messages(
    response_model: Type[BaseModel], prompt_args: dict
):
    """
    Generate messages for an object query.

    This function creates a system message and a user message for querying
    an LLM to generate a response matching a specific model.

    Args:
        response_model (BaseModel): The expected response model.
        prompt_args: Arguments to include in the user prompt.

    Returns:
        list: A list of message dictionaries for the LLM query.
    """
    user_prompt = await compile_user_prompt(**prompt_args) + (
        "\n\nReturn the correct JSON response within a ```json codeblock, not the "
        "JSON_SCHEMA. Use only fields specified by the JSON_SCHEMA and nothing else."
    )
    system_prompt = _compile_obj_system_prompt(response_model)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def parse_obj_response(response_model: Type[BaseModel], content: str):
    """
    Parse an object response from the LLM.

    This function extracts JSON from a code block in the response content
    and constructs an instance of the response model from it.

    Args:
        response_model (BaseModel): The expected response model class.
        content (str): The response content from the LLM.

    Returns:
        An instance of the response model.
    """
    if "```json" in content:
        json_start = content.find("```json") + 7
    elif "```" in content:
        json_start = content.find("```") + 3

    json_end = content.find("```", json_start)
    obj = json.loads(content[json_start:json_end].strip())

    return response_model(**obj)


def parse_block_response(block_type: str, content: str):
    """
    Parse a block response from the LLM.

    This function extracts the content from a code block of the specified type
    in the response content.

    Args:
        block_type (str): The type of block to extract (e.g., "python", "sql").
        content (str): The response content from the LLM.

    Returns:
        str: The extracted content from the code block.
    """
    start = content.rfind(f"```{block_type}") + 3 + len(block_type)
    end = content.find("```", start)

    return content[start:end].strip()


async def _convert_to_dict(obj):
    """
    Recursively normalize an object for serialization.

    This function handles Pydantic BaseModel instances, dictionaries, and lists.
    Other types are returned as-is.

    Args:
        obj: The object to normalize.

    Returns:
        The normalized version of the object.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    elif isinstance(obj, dict):
        return {k: await _convert_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [await _convert_to_dict(v) for v in obj]
    elif isinstance(obj, (int, float, str, bool)):
        return obj
    else:
        return await obj.json()
