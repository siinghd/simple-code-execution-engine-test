from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ValidationError
from typing import List, Optional, Any
import logging
import json

app = FastAPI()

class TestCaseResult(BaseModel):
    input: Optional[Any] = None
    expected_output: Optional[str] = None
    actual_output: Optional[str] = None
    passed: bool
    time: Optional[str] = None
    memory: Optional[str] = None

class ExecutionResult(BaseModel):
    id: str
    results: List[TestCaseResult]
    all_passed: bool
    error: Optional[str] = None
    error_details: Optional[str] = None

@app.post("/callback")
async def handle_callback(request: Request):
    try:
        # First log the raw request body
        raw_body = await request.json()
        print("Raw request body:")
        print(json.dumps(raw_body, indent=2))

        # Try to validate the data
        result = ExecutionResult(**raw_body)
        print("Validated data:")
        print(json.dumps(result.dict(), indent=2))
        return {"status": "received"}
    except ValidationError as e:
        print("Validation error details:")
        for error in e.errors():
            print(f"Field: {error.get('loc', 'unknown')}")
            print(f"Error: {error.get('msg', 'unknown')}")
            print(f"Type: {error.get('type', 'unknown')}")
            print("---")
        raise HTTPException(status_code=422, detail=e.errors())
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)