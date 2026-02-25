"""
Google Drive handler for Telegram repost agent (v3.0).
Upload/download with bundle subfolders; resumable uploads (100 MB chunks).
"""
import os
import io
import re
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_PATH = os.getenv('CREDENTIALS_PATH')
DRIVE_ROOT_FOLDER_ID = os.getenv('DRIVE_ROOT_FOLDER_ID')


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)


def get_or_create_subfolder(subfolder_name: str) -> str:
    """
    Gets the Drive folder ID for a bundle subfolder.
    Creates the subfolder inside TelegramArchive if it doesn't exist.
    Returns the subfolder ID.
    """
    service = get_drive_service()
    safe_name = re.sub(r'[^\w\s\-.]', '', subfolder_name)[:100]

    results = service.files().list(
        q=(f"'{DRIVE_ROOT_FOLDER_ID}' in parents "
           f"and name='{safe_name}' "
           f"and mimeType='application/vnd.google-apps.folder' "
           f"and trashed=false"),
        fields='files(id, name)'
    ).execute()

    files = results.get('files', [])
    if files:
        return files[0]['id']

    folder_metadata = {
        'name': safe_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [DRIVE_ROOT_FOLDER_ID]
    }
    folder = service.files().create(body=folder_metadata, fields='id').execute()
    return folder.get('id')


def upload_to_drive(file_path: str, filename: str, bundle_id: str) -> str:
    """
    Uploads a file into the bundle's subfolder in Drive.
    Uses resumable upload with 100 MB chunks.
    Returns the Drive file ID.
    """
    service = get_drive_service()
    folder_id = get_or_create_subfolder(bundle_id)

    file_metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaFileUpload(
        file_path,
        resumable=True,
        chunksize=100 * 1024 * 1024  # 100 MB chunks
    )
    request = service.files().create(
        body=file_metadata, media_body=media, fields='id,name,size'
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Drive upload: {int(status.progress() * 100)}%", end='\r')

    print(f"\n  Drive upload complete → {bundle_id}/{filename}")
    return response.get('id')


def download_from_drive(drive_file_id: str, destination_path: str):
    """Downloads a file from Drive using chunked download."""
    service = get_drive_service()
    request = service.files().get_media(fileId=drive_file_id)
    fh = io.FileIO(destination_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request, chunksize=100 * 1024 * 1024)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"  Drive download: {int(status.progress() * 100)}%", end='\r')
    fh.close()
    print(f"\n  Drive download complete → {destination_path}")


def get_last_drive_file_in_folder(bundle_id: str) -> dict:
    """
    Returns metadata of the most recently uploaded file in a bundle's subfolder.
    Used for upload verification before Drive deletion.
    """
    service = get_drive_service()
    folder_id = get_or_create_subfolder(bundle_id)
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        orderBy='createdTime desc',
        pageSize=1,
        fields='files(id, name, size)'
    ).execute()
    files = results.get('files', [])
    return files[0] if files else {}


def delete_from_drive(drive_file_id: str):
    """Deletes a file from Drive. Only called after upload verification passes."""
    service = get_drive_service()
    service.files().delete(fileId=drive_file_id).execute()
    print(f"  Drive file deleted: {drive_file_id}")
