import os
import aiofiles
from fastapi import File
from model.file_parser import Chromadb_agent
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from fastapi import UploadFile
from io import BytesIO
import pdfplumber
from model.sqlite import SummaryIndex, AsyncSessionLocal
from sqlalchemy import delete, and_, select
from datetime import datetime
import logging
from pathlib import Path
import docker
import time
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from utils.file_content_extractor import file_content_extract


async def generate_file_summary(file_content: str )->str:
    client = AsyncOpenAI(api_key=os.getenv("api_key"), base_url="https://api.deepseek.com")
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a best literature writer, please complete the following task"},
            {"role": "user", "content": f'''
                Plase create a summary of the content of the file in 1 or 2 sentences and make sure the summary will be good enough and NOT too long.
                Please give me the direct summary and the purpose of the document NO OTHERS
                This is the content of the file:
                {file_content}
            '''}
        ],
        stream=False
    )
    return response.choices[0].message.content

async def file_upload_revert_handler(file: File, session_id: str, chromadb_client: Chromadb_agent, db: AsyncSession):
    ##remove residual file
    if os.path.exists(f"uploads/{session_id}/{file.filename}"):
        os.remove(f"uploads/{session_id}/{file.filename}")

    ##remove residual summary index
    delete_statement = delete(SummaryIndex).where(
        and_(
            SummaryIndex.session_id == session_id,
            SummaryIndex.file_name == file.filename
        )
    )
    await db.execute(delete_statement)
    await db.commit()

    ##remove chromadb collection
    chromadb_client.remove_collection_by_filename(session_id=session_id, filename=file.filename)


async def file_upload_handler(file: File, session_id: str, chromadb_client: Chromadb_agent)->dict[str, str|bool]:
    file_path = Path((f"coding_space/{session_id}/{file.filename}"))
    os.makedirs(file_path.parent, exist_ok=True)
    try:
        ##save the file into the directory
        async with aiofiles.open(file_path, "wb") as buffer:
            content = await file.read()
            await buffer.write(content)

        ##content extract
        # file_content = await extract_content(file=file)
        file_content_result = await file_content_extract(file_path=file_path)
        if file_content_result[0]:
            ##indexing the uploads
            await chromadb_client.index_file(session_id=session_id,  filename=file.filename, text=file_content_result[1])
            ##generate summary and save it into sqlite
            summary = await generate_file_summary(file_content=file_content_result[1])

            ##each corutines must use a different db session
            async with AsyncSessionLocal() as db:
                ##upsert ops the summary index record
                result = await db.execute(
                    select(SummaryIndex).where(
                        and_(
                            SummaryIndex.session_id == session_id,
                            SummaryIndex.file_name == file.filename
                        )
                    )
                )
                existing_summary = result.scalar_one_or_none()
                if existing_summary:
                    existing_summary.summary = summary
                    existing_summary.updated_at = datetime.now()
                else:
                    new_summary = SummaryIndex(
                        session_id=session_id,
                        file_name=file.filename,
                        summary=summary,
                        updated_at=datetime.now()
                    )
                    db.add(new_summary)
                await db.commit()
        else:
            raise Exception(file_content_result[1])
    except Exception as e:
            ##fallback to remove all the associated data
            await file_upload_revert_handler(file=file, session_id=session_id, chromadb_client=chromadb_client, db=db)
            return {"name": file.filename, "result": False}
    return {"name": file.filename, "result": True}


async def summary_fetcher(session_id: str)-> tuple[bool, str | None]:
    async with AsyncSessionLocal() as db:
        select_statement = select(SummaryIndex).where(SummaryIndex.session_id == session_id)
        summaries = await db.execute(select_statement)
        existing_summaries = summaries.scalars().all()
        if existing_summaries:
            converted_summaries = [str({"file_name": each.file_name, "summary": each.summary }) for each in existing_summaries]
            return (True, "\n".join(converted_summaries))
        else:
            return (False, None)
        
def run_docker_commands(thread_id: str, exe_cmds: list[str], code_files: list[dict])->tuple[bool, str]:
    '''
    checking if container with thread_id already running, if not run it
    then running the commands in loop
    '''
    error_result = None
    host_path = os.path.abspath(f"coding_space/{thread_id}")
    if code_files: ##writing code into files
        for each in code_files:
            with open(f"{host_path}/{each.file_name}", "w") as f:
                f.write(each.code_text)
    results = []
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": f"^{thread_id}"})
        if not containers:
            container = client.containers.run(
                image="python:3.11.15-trixie",
                name=thread_id,
                volumes={
                    host_path: {"bind": "/usr/src/app", "mode": "rw"}
                },
                command="tail -f /dev/null",
                detach=True
            )
            for _ in range(10):
                container.reload()
                if container.status == "running":
                    break
                time.sleep(0.5)
        else:
            if containers[0].status != "running":
                containers[0].start()
                containers[0].reload()
            container = containers[0]
        for cmd in exe_cmds:
            exit_code, output = container.exec_run(cmd, workdir="/usr/src/app")
            if exit_code != 0:
                error_result = f"cmd: {cmd}, error: {output.decode('utf-8').strip()}, exit_code: {exit_code}"
                return (False, ";".join(results + [error_result]))
            results.append(f"cmd: {cmd} running successfully, output is \n{'None' if output is None else output.decode('utf-8').strip()}, exit_code: {exit_code}")
        return (True, ";".join(results))
    
    except Exception as e:
        return (False, ";".join(results + [error_result]))


async def safely_ainvoke(*, model: BaseChatModel, message_sequence: list[BaseMessage])->tuple[bool, object]:
    '''
    async invoke response with data type validate and any other exception graceful handle
    '''
    try:
        response = await model.ainvoke(message_sequence)
        if response is None:
            raise ValueError("LLM error: Reponse is None...Please retry")
    except Exception as e:
        return (False, str(e))
    return (True, response)