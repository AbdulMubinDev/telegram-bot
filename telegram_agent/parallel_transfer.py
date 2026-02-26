"""
Parallel file download for Telegram (aria2c-style: multiple connections per file).
Based on mautrix-telegram parallel_file_transfer / FastTelethon gist.
Use for large files (e.g. > 100 MB) to get much higher throughput.
"""
import asyncio
import math
import os
from typing import Optional, List, AsyncGenerator, Union, Awaitable

from telethon import utils, TelegramClient
from telethon.crypto import AuthKey
from telethon.network import MTProtoSender
from telethon.tl import alltlobjects
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import ExportAuthorizationRequest, ImportAuthorizationRequest
from telethon.tl.functions.upload import GetFileRequest
from telethon.tl.types import (
    Document,
    InputFileLocation,
    InputDocumentFileLocation,
    InputPhotoFileLocation,
    InputPeerPhotoFileLocation,
)

TypeLocation = Union[
    Document,
    InputDocumentFileLocation,
    InputPeerPhotoFileLocation,
    InputFileLocation,
    InputPhotoFileLocation,
]


class DownloadSender:
    """One connection downloading every Nth part of a file (stride = connection count)."""

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file: TypeLocation,
        offset: int,
        limit: int,
        stride: int,
        count: int,
    ) -> None:
        self.client = client
        self.sender = sender
        self.request = GetFileRequest(file, offset=offset, limit=limit)
        self.stride = stride
        self.remaining = count

    async def next(self) -> Optional[bytes]:
        if not self.remaining:
            return None
        result = await self.client._call(self.sender, self.request)
        self.remaining -= 1
        self.request.offset += self.stride
        return result.bytes

    def disconnect(self) -> Awaitable[None]:
        return self.sender.disconnect()


class ParallelTransferrer:
    """Multiple MTProto connections downloading the same file in parallel."""

    def __init__(self, client: TelegramClient, dc_id: Optional[int] = None) -> None:
        self.client = client
        self.loop = client.loop
        self.dc_id = dc_id or client.session.dc_id
        self.auth_key = (
            None
            if dc_id and client.session.dc_id != dc_id
            else client.session.auth_key
        )
        self.senders: Optional[List[DownloadSender]] = None

    async def _cleanup(self) -> None:
        if self.senders:
            await asyncio.gather(*[s.disconnect() for s in self.senders])
            self.senders = None

    @staticmethod
    def _get_connection_count(
        file_size: int,
        max_count: int = 16,
        full_size: int = 100 * 1024 * 1024,
    ) -> int:
        """Use more connections for larger files, cap at max_count."""
        if file_size >= full_size:
            return max_count
        return max(1, math.ceil((file_size / full_size) * max_count))

    async def _create_sender(self) -> MTProtoSender:
        dc = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)
        await sender.connect(
            self.client._connection(
                dc.ip_address, dc.port, dc.id,
                loggers=self.client._log,
                proxy=self.client._proxy,
            )
        )
        if not self.auth_key:
            auth = await self.client(ExportAuthorizationRequest(self.dc_id))
            self.client._init_request.query = ImportAuthorizationRequest(
                id=auth.id, bytes=auth.bytes
            )
            req = InvokeWithLayerRequest(alltlobjects.LAYER, self.client._init_request)
            await sender.send(req)
            self.auth_key = sender.auth_key
        return sender

    async def _create_download_sender(
        self,
        file: TypeLocation,
        index: int,
        part_size: int,
        stride: int,
        part_count: int,
    ) -> DownloadSender:
        sender = await self._create_sender()
        return DownloadSender(
            self.client,
            sender,
            file,
            index * part_size,
            part_size,
            stride,
            part_count,
        )

    async def download(
        self,
        file: TypeLocation,
        file_size: int,
        part_size_kb: Optional[float] = None,
        connection_count: Optional[int] = None,
    ) -> AsyncGenerator[bytes, None]:
        connection_count = connection_count or self._get_connection_count(file_size)
        part_size = (part_size_kb or utils.get_appropriated_part_size(file_size)) * 1024
        part_count = math.ceil(file_size / part_size)
        minimum, remainder = divmod(part_count, connection_count)

        def get_part_count() -> int:
            nonlocal remainder
            if remainder > 0:
                remainder -= 1
                return minimum + 1
            return minimum

        self.senders = [
            await self._create_download_sender(
                file, 0, part_size, connection_count * part_size, get_part_count()
            ),
            *await asyncio.gather(
                *[
                    self._create_download_sender(
                        file, i, part_size, connection_count * part_size, get_part_count()
                    )
                    for i in range(1, connection_count)
                ]
            ),
        ]

        part = 0
        while part < part_count:
            tasks = [self.loop.create_task(s.next()) for s in self.senders]
            for task in tasks:
                data = await task
                if data is None:
                    await self._cleanup()
                    return
                yield data
                part += 1

        await self._cleanup()


async def download_file_parallel(
    client: TelegramClient,
    document,
    file_path: str,
    file_size: int,
    progress_callback=None,
    connection_count: Optional[int] = None,
) -> str:
    """
    Download a document using multiple connections (aria2c-style).
    Returns the path to the downloaded file.
    """
    dc_id, location = utils.get_input_location(document)
    transferrer = ParallelTransferrer(client, dc_id)
    downloaded = transferrer.download(location, file_size, connection_count=connection_count)
    with open(file_path, "wb") as out:
        written = 0
        async for chunk in downloaded:
            out.write(chunk)
            written += len(chunk)
            if progress_callback and file_size:
                progress_callback(written, file_size)
    return file_path
