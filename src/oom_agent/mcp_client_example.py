"""
MCP client example for testing the OOM Houdini Agent.
"""

import asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters

from mcp.client.session import ClientSession
from mcp.types import Tool


async def main():
    """Example MCP client that connects to the Houdini agent server."""

    # Start the MCP server as a subprocess
    server_params = StdioServerParameters(
        command="nix-shell",
        args=["-p", "oom-mcp-server", "--run", "mcp-server"],
        env={
            "OOM": "/home/ez/git/oom-dcc",
            "PYTHONPATH": "/home/ez/git/oom-dcc/src",
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # List available tools
            print("=== Available Tools ===")
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                print(f"\n  {tool.name}")
                print(f"    Description: {tool.description}")
                print(f"    Input Schema: {tool.inputSchema}")

            # List available resources
            print("\n=== Available Resources ===")
            resources_result = await session.list_resources()
            for resource in resources_result.resources:
                print(f"  {resource.uri}")
                print(f"    Description: {resource.description}")

            # Example: Create a session
            print("\n=== Example: Create Session ===")
            session_result = await session.call_tool(
                "create_session",
                {"project": "your_project", "sequence": "seq_001", "shot": "sh_001"},
            )
            print(f"Result: {session_result}")

            # Example: Execute code
            print("\n=== Example: Execute Code ===")
            code_result = await session.call_tool(
                "execute_code",
                {
                    "code": "import hou\nprint(f'Current scene: {hou.hipFile.name()}')",
                    "timeout": 10.0,
                },
            )
            print(f"Result: {code_result}")

            # Example: Get status
            print("\n=== Example: Get Status ===")
            status_result = await session.call_tool("get_status", {})
            print(f"Result: {status_result}")


if __name__ == "__main__":
    asyncio.run(main())
