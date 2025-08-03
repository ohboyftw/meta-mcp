#!/usr/bin/env python3
"""
Test script to verify the Meta MCP server works correctly with MCP protocol.
"""

import asyncio
import subprocess
import sys
from mcp import ClientSession
from mcp.client.stdio import stdio_client


async def test_mcp_server():
    """Test the Meta MCP server using the MCP protocol client."""
    print("Starting Meta MCP server test...")

    try:
        # Connect to the server using stdio transport
        from mcp.client.stdio import StdioServerParameters
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "meta_mcp", "serve", "--stdio"]
        )
        
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Initialize the session
                await session.initialize()
                print("✅ Session initialized successfully")

                # List available tools
                tools_result = await session.list_tools()
                print(f"✅ Found {len(tools_result.tools)} tools:")
                for tool in tools_result.tools:
                    print(f"  - {tool.name}: {tool.description[:80]}...")

                # Test search functionality
                print("\n🔍 Testing search_mcp_servers...")
                search_result = await session.call_tool(
                    "search_mcp_servers", arguments={"query": "file", "limit": 2}
                )

                if search_result.content:
                    content = (
                        search_result.content[0].text
                        if hasattr(search_result.content[0], "text")
                        else str(search_result.content[0])
                    )
                    print(f"✅ Search completed. Result preview: {content[:200]}...")
                else:
                    print("❌ Search returned no content")

                # Test server info functionality
                print("\n📋 Testing get_server_info...")
                info_result = await session.call_tool(
                    "get_server_info", arguments={"server_name": "filesystem"}
                )

                if info_result.content:
                    content = (
                        info_result.content[0].text
                        if hasattr(info_result.content[0], "text")
                        else str(info_result.content[0])
                    )
                    print(
                        f"✅ Server info completed. Result preview: {content[:200]}..."
                    )
                else:
                    print("❌ Server info returned no content")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_mcp_server())
