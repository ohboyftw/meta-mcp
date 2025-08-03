"""
Base classes for Meta MCP tools following the Serena FastMCP pattern.
"""

import traceback
from abc import ABC, abstractmethod

from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata


class Tool(ABC):
    """Base class for all Meta MCP tools following Serena's pattern."""

    def __init__(self):
        """Initialize the tool."""
        pass

    @classmethod
    def get_name_from_cls(cls) -> str:
        """Get tool name from class name."""
        name = cls.__name__
        if name.endswith("Tool"):
            name = name[:-4]
        # Convert to snake_case
        name = "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip(
            "_"
        )
        return name

    def get_name(self) -> str:
        """Get tool name."""
        return self.get_name_from_cls()

    @abstractmethod
    def apply(self, **kwargs) -> str:
        """
        Apply the tool with the given arguments.

        This method must be implemented by all tool subclasses.
        It should return a string result that will be automatically
        wrapped by the FastMCP framework.
        """
        pass

    def get_apply_docstring(self) -> str:
        """Get the docstring for the apply method."""
        docstring = self.apply.__doc__
        if not docstring:
            raise AttributeError(f"apply method has no docstring in {self.__class__}.")
        return docstring.strip()

    def get_apply_fn_metadata(self) -> FuncMetadata:
        """Get metadata for the apply method."""
        return func_metadata(self.apply, skip_names=["self"])

    def apply_ex(
        self, log_call: bool = True, catch_exceptions: bool = True, **kwargs
    ) -> str:
        """
        Apply the tool with logging and exception handling.

        This follows Serena's pattern exactly - returns a string that
        FastMCP will automatically wrap in the proper MCP response format.
        """
        try:
            if log_call:
                print(f"Calling {self.get_name()} with args: {kwargs}")

            # Call the actual tool implementation
            result = self.apply(**kwargs)

            if log_call:
                print(f"Result: {result[:200]}{'...' if len(result) > 200 else ''}")

            return result

        except Exception as e:
            if not catch_exceptions:
                raise

            error_msg = f"Error executing tool {self.get_name()}: {str(e)}"
            if log_call:
                print(f"Error: {error_msg}")
                print(f"Traceback: {traceback.format_exc()}")

            return error_msg
