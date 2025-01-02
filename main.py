from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from celery import Celery
import requests
import uuid
import subprocess
from dotenv import load_dotenv
import os
import json
import shutil
import tempfile

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Configure Celery
celery = Celery(
    'code_execution_app',
    broker=os.getenv('CELERY_BROKER_URL'),
    backend=os.getenv('CELERY_RESULT_BACKEND')
)

class TestCase(BaseModel):
    input: list
    expected_output: str

class CodeExecutionRequest(BaseModel):
    language: str
    code: str
    function_name: str
    imports: list
    test_cases: list[TestCase]
    callback_url: str

def validate_input(data: CodeExecutionRequest):
    if data.language not in ['python', 'js', 'java', 'rust', 'go', 'cpp']:
        raise ValueError("Invalid language")
    if not isinstance(data.code, str):
        raise ValueError("Invalid code")
    if not isinstance(data.imports, list):
        raise ValueError("Invalid imports")
    if not isinstance(data.test_cases, list):
        raise ValueError("Invalid test cases")
    for test_case in data.test_cases:
        if not isinstance(test_case.input, list) or not isinstance(test_case.expected_output, str):
            raise ValueError("Invalid test case data")

def run_code_in_docker(language, code, function_name, imports, test_cases):
    with tempfile.TemporaryDirectory() as temp_dir:
        if language == 'python':
            return run_python_code(code, function_name, imports, test_cases, temp_dir)
        elif language == 'js':
            return run_js_code(code, function_name, imports, test_cases, temp_dir)
        
        else:
            return "Invalid language specified."

def run_python_code(code, function_name, imports, test_cases, temp_dir):
    script = ""
    if imports:
        for imp in imports:
            script += f"import {imp}\n"
    script += f"{code}\n\n"
    script += "import json\n"
    script += "import time\n" 
    script += "test_cases = [\n"
    for test_case in test_cases:
        script += f"    ({json.dumps(test_case['input'])}, '{test_case['expected_output']}'),\n"
    script += "]\n"
    script += f"""
results = []
for inputs, expected in test_cases:
    try:
        start_time = time.perf_counter()
        result = {function_name}(*inputs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        result_str = str(result)
        passed = result_str == expected
        results.append((inputs, expected, result_str, passed, duration))
    except Exception as e:
        results.append((inputs, expected, str(e), False, "0.0"))
for inputs, expected, result, passed, duration in results:
    print(json.dumps({{"inputs": inputs, "expected": expected, "result": result, "passed": passed, "time": duration}}))
"""
    script_path = os.path.join(temp_dir, "temp_script.py")
    with open(script_path, "w") as f:
        f.write(script)

    docker_run_command = (
        f"docker run --rm --user {os.getuid()}:{os.getgid()} -v {temp_dir}:/usr/src/app -w /usr/src/app --network none --memory=256m --cpus=1 "
        f"--ulimit cpu=10 --ulimit nofile=512 python:latest python temp_script.py"
    )
    process = subprocess.Popen(docker_run_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    if process.returncode == 0:
        return stdout.decode('utf-8')
    else:
        return stderr.decode('utf-8') or stdout.decode('utf-8')

def run_js_code(code, function_name, imports, test_cases, temp_dir):
    script = f"{code}\n\n"
    script += "const test_cases = [\n"
    for test_case in test_cases:
        script += f"    [{json.dumps(test_case['input'])}, '{test_case['expected_output']}'],\n"
    script += "];\n"
    script += f"""
const results = [];
for (const [inputs, expected] of test_cases) {{
    try {{
        const start = performance.now();
        const result = {function_name}(...inputs);
        const end = performance.now();
        const duration = (end - start).toString();
        const result_str = result.toString();
        const passed = result_str === expected;
        results.push({{inputs, expected, result: result_str, passed, time: duration}});
    }} catch (e) {{
        results.push({{inputs, expected, result: e.toString(), passed: false, time: "0.0"}});
    }}
}}
for (const {{inputs, expected, result, passed,time}} of results) {{
    console.log(JSON.stringify({{inputs, expected, result, passed,time}}));
}}
"""
    script_path = os.path.join(temp_dir, "temp_script.js")
    with open(script_path, "w") as f:
        f.write(script)

    docker_run_command = (
        f"docker run --rm --user {os.getuid()}:{os.getgid()} -v {temp_dir}:/usr/src/app -w /usr/src/app --network none --memory=256m --cpus=1 "
        f"--ulimit cpu=10 --ulimit nofile=512 node:latest node temp_script.js"
    )
    process = subprocess.Popen(docker_run_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    if process.returncode == 0:
        return stdout.decode('utf-8')
    else:
        return stderr.decode('utf-8') or stdout.decode('utf-8')
    

def run_java_code(code, function_name, imports, test_cases, temp_dir):
    # Create the Java class wrapper
    class_name = "Solution"
    java_code = "import java.util.*;\n"
    java_code += "import com.google.gson.Gson;\n"  # For JSON handling
    
    # Add user imports
    if imports:
        for imp in imports:
            java_code += f"import {imp};\n"
    
    # Start class definition
    java_code += f"""
public class {class_name} {{
    {code}

    public static void main(String[] args) {{
        Solution solution = new Solution();
        Gson gson = new Gson();
        
        // Test cases
        List<TestCase> testCases = new ArrayList<>();
"""

    # Add test cases
    for test_case in test_cases:
        input_values = json.dumps(test_case['input'])
        expected = test_case['expected_output']
        java_code += f"""
        testCases.add(new TestCase(
            gson.fromJson("{input_values}", Object[].class),
            "{expected}"
        ));
"""

    # Add test execution code
    java_code += """
        for (TestCase testCase : testCases) {
            try {
                long startTime = System.nanoTime();
                Object result = null;
                
                // Convert input parameters to appropriate types and call the method
                Object[] inputs = testCase.inputs;
                switch (inputs.length) {
                    case 0:
                        result = solution.""" + function_name + """();
                        break;
                    case 1:
                        result = solution.""" + function_name + """(convertParameter(inputs[0]));
                        break;
                    case 2:
                        result = solution.""" + function_name + """(
                            convertParameter(inputs[0]),
                            convertParameter(inputs[1]));
                        break;
                    case 3:
                        result = solution.""" + function_name + """(
                            convertParameter(inputs[0]),
                            convertParameter(inputs[1]),
                            convertParameter(inputs[2]));
                        break;
                    // Add more cases if needed
                }
                
                long endTime = System.nanoTime();
                double duration = (endTime - startTime) / 1e6; // Convert to milliseconds
                
                String resultStr = String.valueOf(result);
                boolean passed = resultStr.equals(testCase.expected);
                
                TestResult testResult = new TestResult(
                    testCase.inputs,
                    testCase.expected,
                    resultStr,
                    passed,
                    String.valueOf(duration)
                );
                
                System.out.println(gson.toJson(testResult));
                
            } catch (Exception e) {
                TestResult testResult = new TestResult(
                    testCase.inputs,
                    testCase.expected,
                    e.toString(),
                    false,
                    "0.0"
                );
                System.out.println(gson.toJson(testResult));
            }
        }
    }
    
    // Helper class for test cases
    static class TestCase {
        Object[] inputs;
        String expected;
        
        TestCase(Object[] inputs, String expected) {
            this.inputs = inputs;
            this.expected = expected;
        }
    }
    
    // Helper class for test results
    static class TestResult {
        Object[] inputs;
        String expected;
        String result;
        boolean passed;
        String time;
        
        TestResult(Object[] inputs, String expected, String result, boolean passed, String time) {
            this.inputs = inputs;
            this.expected = expected;
            this.result = result;
            this.passed = passed;
            this.time = time;
        }
    }
    
    // Helper method to convert parameters to appropriate types
    private static Object convertParameter(Object param) {
        if (param instanceof List) {
            List<?> list = (List<?>) param;
            // Convert to array based on the first element's type
            if (!list.isEmpty()) {
                Object first = list.get(0);
                if (first instanceof Integer) {
                    return list.stream().map(i -> ((Number)i).intValue())
                                      .mapToInt(Integer::intValue)
                                      .toArray();
                } else if (first instanceof String) {
                    return list.toArray(new String[0]);
                }
                // Add more type conversions as needed
            }
            return new Object[0];
        }
        // Handle primitive type conversions
        if (param instanceof Number) {
            if (((Number)param).doubleValue() % 1 == 0) {
                return ((Number)param).intValue();
            }
            return ((Number)param).doubleValue();
        }
        return param;
    }
}}"""

    # Write the Java code to a file
    java_file_path = os.path.join(temp_dir, f"{class_name}.java")
    with open(java_file_path, "w") as f:
        f.write(java_code)

    # Copy the gson.jar to the temp directory
    gson_jar = "/path/to/gson.jar"  # You'll need to provide this
    shutil.copy2(gson_jar, temp_dir)

    # Compile the Java code
    compile_command = (
        f"docker run --rm --user {os.getuid()}:{os.getgid()} "
        f"-v {temp_dir}:/usr/src/app -w /usr/src/app "
        f"--network none --memory=256m --cpus=1 "
        f"openjdk:11 javac -cp gson.jar {class_name}.java"
    )
    
    compile_process = subprocess.Popen(compile_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    compile_stdout, compile_stderr = compile_process.communicate()

    if compile_process.returncode != 0:
        return compile_stderr.decode('utf-8')

    # Run the compiled Java code
    run_command = (
        f"docker run --rm --user {os.getuid()}:{os.getgid()} "
        f"-v {temp_dir}:/usr/src/app -w /usr/src/app "
        f"--network none --memory=256m --cpus=1 "
        f"openjdk:11 java -cp .:/usr/src/app/gson.jar {class_name}"
    )
    
    run_process = subprocess.Popen(run_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    run_stdout, run_stderr = run_process.communicate()

    if run_process.returncode == 0:
        return run_stdout.decode('utf-8')
    else:
        return run_stderr.decode('utf-8') or run_stdout.decode('utf-8')
    
def try_parse_list(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value

def get_docker_memory_usage(container_name):
    docker_stats_command = f"docker stats {container_name} --no-stream --format '{{{{.MemUsage}}}}'"
    stats_process = subprocess.Popen(docker_stats_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stats_stdout, stats_stderr = stats_process.communicate()

    if stats_process.returncode == 0:
        memory_usage = stats_stdout.decode('utf-8').strip().split('/')[0].strip()
    else:
        memory_usage = "N/A"

    return memory_usage

@celery.task(name='code_execution_app.execute_code_task')
def execute_code_task(data, id):
    execution_id = id
    language = data['language']
    code = data['code']
    function_name = data['function_name']
    imports = data['imports']
    test_cases = data['test_cases']
    callback_url = data['callback_url']
    results = []

    actual_output = run_code_in_docker(language, code, function_name, imports, test_cases)
    if not actual_output:
        actual_output = "No output from Docker execution."

    # Parse the single JSON output from Java
    try:
        # Clean up any leading/trailing whitespace
        actual_output = actual_output.strip()
        print(f"Processing output: {actual_output}")  # Debug log
        
        result_json = json.loads(actual_output)
        print(f"Parsed JSON: {result_json}")  # Debug log
        
        # Create a single result object in our expected format
        result = {
            'input': result_json.get('inputs', []),  # Use get() with default
            'expected_output': result_json.get('expected', ''),
            'actual_output': result_json.get('result', ''),
            'passed': result_json.get('passed', False),
            'time': str(result_json.get('time', 0.0)),
            'memory': 'N/A'
        }
        
        results.append(result)
        
        response_payload = {
            'id': execution_id,
            'results': results,
            'all_passed': result.get('passed', False)
        }

    except Exception as e:
        print(f"Error processing results: {str(e)}")  # Debug log
        response_payload = {
            'id': execution_id,
            'results': [],
            'all_passed': False,
            'error': f"Error processing results: {str(e)}",
            'error_details': actual_output
        }

    try:
        print(f"Sending callback payload: {json.dumps(response_payload, indent=2)}")
        response = requests.post(callback_url, json=response_payload)
        print(f"Callback response status: {response.status_code}")
        print(f"Callback response content: {response.text}")
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error sending callback: {e}")

    return response_payload
@app.post("/execute")
async def execute_code(request: CodeExecutionRequest):
    try:
        id = str(uuid.uuid4())
        validate_input(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    execute_code_task.delay(request.dict(), id)
    return {"message": "Code execution started", "id": id}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)