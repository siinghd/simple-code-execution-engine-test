# Code Execution Engine

A secure, containerized code execution service that runs user code in isolated Docker containers and returns JSON results via HTTP callbacks.

## Features

- **Multi-language support**: Python, JavaScript, Java, C++, Go
- **Docker isolation**: Each execution runs in isolated containers with resource limits
- **Async processing**: Uses Celery for queuing and background execution
- **HTTP callbacks**: Results delivered to your specified callback URL
- **Test-driven**: Execute functions with multiple test cases and get detailed results
- **Security**: No network access for executing code, input validation, timeouts

## Architecture

```
HTTP Request → FastAPI → Celery Queue → Docker Container → Callback
```

## Setup

1. **Install dependencies**:
```bash
pip install -r requirements.txt
```

2. **Set environment variables**:
```bash
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"
```

3. **Start the services**:
```bash
# Terminal 1: Start FastAPI server
python run_server.py

# Terminal 2: Start Celery worker
python celery_worker.py

# Terminal 3: Start callback receiver (for testing)
python callback_receiver.py
```

## Run Like

### JavaScript Example

**Request:**
```bash
curl -X POST "http://localhost:8000/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "language": "js",
    "code": "function findMedianSortedArrays(nums1, nums2) {\n  if (nums1.length > nums2.length) {\n    return findMedianSortedArrays(nums2, nums1);\n  }\n  const m = nums1.length;\n  const n = nums2.length;\n  let low = 0, high = m;\n  while (low <= high) {\n    const cut1 = Math.floor((low + high) / 2);\n    const cut2 = Math.floor((m + n + 1) / 2) - cut1;\n    const left1 = cut1 === 0 ? -Infinity : nums1[cut1 - 1];\n    const left2 = cut2 === 0 ? -Infinity : nums2[cut2 - 1];\n    const right1 = cut1 === m ? Infinity : nums1[cut1];\n    const right2 = cut2 === n ? Infinity : nums2[cut2];\n    if (left1 <= right2 && left2 <= right1) {\n      if ((m + n) % 2 === 0) {\n        return (Math.max(left1, left2) + Math.min(right1, right2)) / 2.0;\n      } else {\n        return Math.max(left1, left2);\n      }\n    } else if (left1 > right2) {\n      high = cut1 - 1;\n    } else {\n      low = cut1 + 1;\n    }\n  }\n  return 1.0;\n}",
    "function_name": "findMedianSortedArrays",
    "imports": [],
    "test_cases": [
      {
        "input": [[1, 3], [2]],
        "expected_output": "2"
      },
      {
        "input": [[1, 2], [3, 4]],
        "expected_output": "2.5"
      },
      {
        "input": [[0, 0], [0, 0]],
        "expected_output": "0"
      },
      {
        "input": [[1, 3], [2, 7]],
        "expected_output": "2.5"
      }
    ],
    "callback_url": "http://localhost:5001/callback"
  }'
```

**Response:**
```json
{
  "message": "Code execution task accepted",
  "id": "eb7411b2-b200-442f-97f5-c9164b31c974"
}
```

**Callback Payload:**
```json
{
  "id": "eb7411b2-b200-442f-97f5-c9164b31c974",
  "results": [
    {
      "input": [[1, 3], [2]],
      "expected_output": "2",
      "actual_output": "2",
      "passed": true,
      "time": "0.0457 ms",
      "memory": "N/A"
    },
    {
      "input": [[1, 2], [3, 4]],
      "expected_output": "2.5",
      "actual_output": "2.5",
      "passed": true,
      "time": "0.0021 ms",
      "memory": "N/A"
    },
    {
      "input": [[0, 0], [0, 0]],
      "expected_output": "0",
      "actual_output": "0",
      "passed": true,
      "time": "0.0011 ms",
      "memory": "N/A"
    },
    {
      "input": [[1, 3], [2, 7]],
      "expected_output": "2.5",
      "actual_output": "2.5",
      "passed": true,
      "time": "0.0009 ms",
      "memory": "N/A"
    }
  ],
  "all_passed": true,
  "error": null,
  "error_details": null
}
```

### Python Example

**Request:**
```bash
curl -X POST "http://localhost:8000/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "code": "def add_numbers(a, b):\n    return a + b",
    "function_name": "add_numbers",
    "imports": [],
    "test_cases": [
      {
        "input": [2, 3],
        "expected_output": "5"
      },
      {
        "input": [10, -5],
        "expected_output": "5"
      }
    ],
    "callback_url": "http://localhost:5001/callback"
  }'
```

**Callback Payload:**
```json
{
  "id": "12345678-1234-1234-1234-123456789012",
  "results": [
    {
      "input": [2, 3],
      "expected_output": "5",
      "actual_output": "5",
      "passed": true,
      "time": "0.0123 ms",
      "memory": "N/A"
    },
    {
      "input": [10, -5],
      "expected_output": "5",
      "actual_output": "5",
      "passed": true,
      "time": "0.0098 ms",
      "memory": "N/A"
    }
  ],
  "all_passed": true,
  "error": null,
  "error_details": null
}
```

### Java Example

**Request:**
```bash
curl -X POST "http://localhost:8000/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "language": "java",
    "code": "class Solution {\n    public int addNumbers(int a, int b) {\n        return a + b;\n    }\n}",
    "function_name": "addNumbers",
    "imports": [],
    "test_cases": [
      {
        "input": [5, 7],
        "expected_output": "12"
      }
    ],
    "callback_url": "http://localhost:5001/callback"
  }'
```

### Error Example

**Request with syntax error:**
```bash
curl -X POST "http://localhost:8000/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "language": "python",
    "code": "def broken_function(x):\n    return x +",
    "function_name": "broken_function",
    "imports": [],
    "test_cases": [
      {
        "input": [5],
        "expected_output": "5"
      }
    ],
    "callback_url": "http://localhost:5001/callback"
  }'
```

**Callback Payload:**
```json
{
  "id": "error-example-id",
  "results": [
    {
      "input": [5],
      "expected_output": "5",
      "actual_output": "Execution Failed",
      "passed": false,
      "time": "0.0 ms",
      "memory": "N/A"
    }
  ],
  "all_passed": false,
  "error": "Execution environment error",
  "error_details": "Execution failed with exit code 1.\n  File \"/usr/src/app/temp_script.py\", line 2\n    return x +\n             ^\nSyntaxError: invalid syntax"
}
```

## API Reference

### POST /execute

Submits code for execution.

**Request Body:**
- `language` (string): One of "python", "js", "java", "cpp", "go"
- `code` (string): The source code containing the function to test
- `function_name` (string): Name of the function to call
- `imports` (array): List of imports/modules to include (language-specific)
- `test_cases` (array): List of test cases with `input` and `expected_output`
- `callback_url` (string): URL where results will be POSTed

**Response:**
- `message` (string): Confirmation message
- `id` (string): Unique execution ID for tracking

## Resource Limits

- **Memory**: 256MB for Python/JS, 512MB for Java/C++/Go
- **CPU**: 1 core maximum
- **Time**: 15-30 seconds depending on language
- **Network**: Disabled during execution

## Supported Languages

| Language   | Container      | Features                    |
|------------|----------------|----------------------------|
| Python     | python:3.10    | Standard library, JSON     |
| JavaScript | node:18        | ES6+, performance timing   |
| Java       | openjdk:11     | Reflection, Gson, generics |
| C++        | gcc:latest     | C++17, STL, chrono         |
| Go         | golang:1.21    | Standard library, JSON     |



## Docker Requirements

Make sure Docker is installed and running. The service will automatically pull required images on first use.

## Environment Variables

- `CELERY_BROKER_URL`: Redis URL for Celery message broker
- `CELERY_RESULT_BACKEND`: Redis URL for Celery result storage
- `HOST`: FastAPI server host (default: 127.0.0.1)
- `PORT`: FastAPI server port (default: 8000)