from __future__ import annotations

import base64
from typing import Any, AsyncIterator

from pydantic import BaseModel
from contextlib import asynccontextmanager
from aiohttp import BasicAuth, ClientSession, ClientResponse, ClientResponseError  # pyright: reportUnusedImport=false

__all__: tuple[str, ...] = ('GithubClient', 'FileData', 'TreeNode', 'Repository', 'create_client')

# Constants
BASE_URL = 'https://api.github.com'
REPO_URL = f"{BASE_URL}/repos/{{0}}/{{1}}"
REPO_CONTENTS_URL = f"{BASE_URL}/{REPO_URL}/contents"


class GithubClient:
    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def fetch_repo(self, owner: str, repo: str):
        """|coro| Retrieves a :class:`.Repository` from github.

        Parameters
        ----------
        owner: :class:`str`
            The owner of this repository.
        repo: :class:`str`
            The repository name.

        Returns
        -------
        :class:`.Repository`
            The respective repository.

        Raises
        ------
        :class:`.ClientResponseError`
            aiohttp client response error from :meth:`.ClientResponse.raise_for_status`
        """
        async with self.session.get(REPO_URL.format(owner, repo)) as response:
            response.raise_for_status()
            return Repository(**await response.json(), client=self)


class FileData(BaseModel):
    sha: str
    node_id: str
    size: int
    url: str
    content: str
    encoding: str

    def decode(self):
        return base64.b64decode(self.content).decode()


class TreeNode(BaseModel):
    path: str
    mode: str
    type: str
    sha: str
    size: int | None
    url: str
    client: GithubClient

    class Config:
        arbitrary_types_allowed = True

    async def fetch_filedata(self) -> FileData | list[TreeNode]:
        async with self.client.session.get(self.url) as response:
            response.raise_for_status()
            if self.type == "blob":
                return FileData(**await response.json())
            elif self.type == "tree":
                data = await response.json()
                return [TreeNode(**node, client=self.client) for node in data['tree']]
            else:
                raise RuntimeError(f'Unknown node type {self.type!r}')


class Repository(BaseModel):
    # Let pydantic parse this for us :lazy:
    id: int
    name: str
    full_name: str
    html_url: str
    description: str
    trees_url: str
    default_branch: str
    client: GithubClient

    class Config:
        arbitrary_types_allowed = True

    async def fetch_tree(self, branch: str | None = None, recursive: bool = True) -> list[TreeNode]:
        """|coro| Gets a list of :class:`.TreeNode` from github.

        Parameters
        ----------
        owner: :class:`str`
            The owner of this repository.
        repo: :class:`str`
            The repository name.

        Returns
        -------
        list[:class:`.TreeNode`]
            The nodes.

        Raises
        ------
        :class:`.ClientResponseError`
            aiohttp client response error from :meth:`.ClientResponse.raise_for_status`
        """
        branch = branch or self.default_branch
        url = self.trees_url.format(**{'/sha': f'/{branch}'})
        async with self.client.session.get(url, params={'recursive': int(recursive)}) as response:
            response.raise_for_status()
            data = await response.json()
            return [TreeNode(**node, client=self.client) for node in data['tree']]


@asynccontextmanager
async def create_client(token: str) -> AsyncIterator[GithubClient]:
    async with ClientSession(headers={'Authorization': f'Bearer {token}'}) as session:
        yield GithubClient(session)


if __name__ == '__main__':
    import os
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()

    import discord

    async def main():
        async with create_client(os.environ['GITHUB_ORG_TOKEN']) as client:
            repo = await client.fetch_repo('DuckBot-Discord', 'DuckBot')

            tree = await repo.fetch_tree()

            def file_check(node: TreeNode):
                return node.path == 'cogs/economy/_base.py'

            node = discord.utils.find(file_check, tree)

            if node:
                file_data = await node.fetch_filedata()
                if not isinstance(file_data, list):
                    print(file_data.decode())

    asyncio.run(main())
