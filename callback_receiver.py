from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError
from typing import List, Optional
import logging
import json
app = FastAPI()

class TestCaseResult(BaseModel):
    input: Optional[List]  # Use Optional to handle potential None values
    expected_output: Optional[str]
    actual_output: Optional[str]
    passed: bool
    time: Optional[str]
    memory: Optional[str]


class ExecutionResult(BaseModel):
    id: str
    results: List[TestCaseResult]
    all_passed: bool
    error: Optional[str]
    error_details: Optional[str]

@app.post("/callback")
async def handle_callback(result: ExecutionResult):
    try:
        print("Received callback with data:")
        print(json.dumps(result.dict(), indent=2)) 
        return {"status": "received"}
    except ValidationError as e:
        logging.error(f"Validation error: {e.json()}")
        raise HTTPException(status_code=422, detail=e.errors())

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
