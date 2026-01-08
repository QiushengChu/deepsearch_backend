import os
import shutil
from typing import List
from fastapi.responses import JSONResponse, FileResponse
from fastapi import status, APIRouter, UploadFile, HTTPException, Depends
from model.memory import checkpointer_manager
from utils.helper_funcs import file_upload_handler, summary_fetcher
import asyncio
from model.file_parser import Chromadb_agent
from model.dependency.dependencies import get_chromadb_agent_singleton, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete
from model.sqlite import SummaryIndex
import mimetypes
from urllib.parse import quote


session_router =  APIRouter()
    
@session_router.post("/api/{session_id}/upload")
async def file_upload(
        session_id: str, 
        files: List[UploadFile], 
        chromadb_agent: Chromadb_agent = Depends(get_chromadb_agent_singleton)
    )->JSONResponse:
    try:
        # session_exist = await checkpointer_manager.thread_checker(session_id=session_id)
        # if not session_exist:
        #     return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={
        #         "error": f"session {session_id} does not exist.."
        #     })
        ##creating files async
        os.makedirs(f"uploads/{session_id}", exist_ok=True)
        corutines = [file_upload_handler(
            file=file, 
            session_id=session_id, 
            chromadb_client=chromadb_agent
        ) for file in files]

        results = await asyncio.gather(*corutines)
        failed_uploads = list(filter(lambda x: x["result"] == False, results))

        if failed_uploads:
            failed_names = (", ").join([upload["name"] for upload in failed_uploads])
            return JSONResponse(status_code=status.HTTP_201_CREATED, content=f"{failed_names} failed in uploads")
        else:
            return JSONResponse(status_code=status.HTTP_201_CREATED, content="files has been uploaded.")
        
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Server Side Error: {e}")
    

@session_router.delete("/api/{session_id}")
async def delete_files_index_via_session(
        session_id: str, 
        chromadb_agent: Chromadb_agent = Depends(get_chromadb_agent_singleton),
        db: AsyncSession = Depends(get_db)
    )->JSONResponse:
    try:
        ##remove session from langgraph session
        result = await checkpointer_manager.remove_thread(session_id=session_id)
        # if result["result"] == False:
        #     return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={
        #         "error": f"{session_id} is not valid"
        #     })

        chromadb_agent = Chromadb_agent() #remove the collection in chromadb
        result = chromadb_agent.remove_collection_by_session_id(session_id=session_id)

        ##remove the directory
        if os.path.isdir(f"uploads/{session_id}"):
            shutil.rmtree(f"uploads/{session_id}")

        ##remove summary index in the sqlite
        delete_statement = delete(SummaryIndex).where(SummaryIndex.session_id == session_id)
        await db.execute(delete_statement)
        await db.commit()

        return JSONResponse(status_code=status.HTTP_200_OK, content=result[0])
    except Exception as e:
        raise HTTPException(state_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@session_router.get("/api/file/download/{session_id}/{file_name}")
def get_file_download(session_id: str, file_name: str):
    download_path = f"uploads/{session_id}/{file_name}"
    try:
        if not os.path.exists(download_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{file_name} does not exist")
        if not os.path.isfile(download_path):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{file_name} is not a valid file")
        
        mime_type, _ = mimetypes.guess_type(download_path)
        if mime_type is None:
            mime_type = "application/octet-stream"
        
        viewable_types = [
            'application/pdf',
            'text/plain',
            'text/csv',
            'application/json',
            'text/html',
            'text/xml'
        ]
        
        image_types = [
            'image/jpeg', 'image/jpg', 'image/png', 
            'image/gif', 'image/svg+xml', 'image/webp'
        ]
        
        viewable_types.extend(image_types)

        if mime_type in viewable_types:
            disposition = f"inline; filename=\"{quote(file_name)}\""
        else:
            disposition = f"attachment; filename=\"{quote(file_name)}\""

        return FileResponse(
            path=download_path,
            filename=file_name,
            media_type=mime_type,
            headers={
                "Content-Disposition": disposition
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error downloading file: {str(e)}")
    