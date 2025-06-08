# main.py
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Type

import requests
from celery import Celery
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

class TestCase(BaseModel):
    input: List[Any]
    expected_output: str

class CodeExecutionRequest(BaseModel):
    language: str
    code: str
    function_name: str
    imports: List[str] = Field(default_factory=list)
    test_cases: List[TestCase]
    callback_url: str

class ExecutionResult(BaseModel):
    input: List[Any]
    expected_output: str
    actual_output: str
    passed: bool
    time: str
    memory: str = "N/A"

class CallbackPayload(BaseModel):
    id: str
    results: List[ExecutionResult]
    all_passed: bool
    error: Optional[str] = None
    error_details: Optional[str] = None

app = FastAPI(title="Code Execution Engine", version="1.0")

celery = Celery(
    'code_execution_app',
    broker=os.getenv('CELERY_BROKER_URL'),
    backend=os.getenv('CELERY_RESULT_BACKEND')
)

# prevent multiple worker instances from picking up the same task
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    task_track_started=True,
    task_time_limit=600,
    worker_prefetch_multiplier=1,
    task_routes={
        'code_execution_app.execute_code_task': {'queue': 'code_execution'},
    },
)

SUPPORTED_LANGUAGES = ['python', 'js', 'java', 'cpp', 'go']

def validate_input(data: CodeExecutionRequest):
    """validates request data to prevent malicious input"""
    if data.language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Invalid language. Supported: {', '.join(SUPPORTED_LANGUAGES)}")
    if not data.code.strip():
        raise ValueError("Code cannot be empty")
    if not data.function_name.strip():
        raise ValueError("Function name cannot be empty")
    if not isinstance(data.imports, list):
        raise ValueError("Imports must be a list")
    if not data.test_cases:
        raise ValueError("Test cases list cannot be empty")
    if not data.callback_url.strip():
        raise ValueError("Callback URL cannot be empty")

    for i, tc in enumerate(data.test_cases):
        if not isinstance(tc, TestCase):
            raise ValueError(f"Test case at index {i} is not a valid TestCase object.")
        if not isinstance(tc.input, list):
            raise ValueError(f"Input for test case {i} must be a list.")
        if not isinstance(tc.expected_output, str):
            raise ValueError(f"Expected output for test case {i} must be a string.")

def _run_docker_command(command: str, timeout_seconds: int = 30) -> (str, Optional[str]):
    """executes user code in isolated docker container with resource limits"""
    print(f"Executing Docker Command:\n{command}\n")
    stdout_decoded = ""
    stderr_decoded = ""
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(timeout=timeout_seconds)

        stdout_decoded = stdout.decode('utf-8', errors='replace')
        stderr_decoded = stderr.decode('utf-8', errors='replace')

        if process.returncode == 0:
            print("Docker execution successful.")
            if stderr_decoded:
                 print(f"Docker stderr (Return Code 0):\n{stderr_decoded}")
            return stdout_decoded, None
        else:
            # detect timeout vs other execution failures for better error messages
            is_timeout = process.returncode in [124, 137] or "Timeout" in stderr_decoded or "killed" in stderr_decoded.lower()
            if is_timeout:
                error_message = f"Execution timed out after {timeout_seconds} seconds."
                print(f"Docker execution failed (Timeout): Return Code {process.returncode}\nStderr:\n{stderr_decoded}")
                return stdout_decoded, error_message + "\n" + stderr_decoded.strip()
            else:
                error_message = f"Execution failed with exit code {process.returncode}."
                print(f"Docker execution failed: Return Code {process.returncode}\nStderr:\n{stderr_decoded}")
                full_error_details = (stderr_decoded.strip() + "\n" + stdout_decoded.strip()).strip()
                return stdout_decoded, error_message + "\n" + full_error_details

    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        stdout_decoded = stdout.decode('utf-8', errors='replace')
        stderr_decoded = stderr.decode('utf-8', errors='replace')
        error_message = f"Execution explicitly timed out after {timeout_seconds} seconds."
        print(error_message)
        full_error_details = (stderr_decoded.strip() + "\n" + stdout_decoded.strip()).strip()
        return stdout_decoded, error_message + "\n" + full_error_details

    except Exception as e:
        error_message = f"Failed to run Docker command: {type(e).__name__}: {e}"
        print(error_message)
        return "", error_message

def run_python_code(code: str, function_name: str, imports: List[str], test_cases: List[TestCase], temp_dir: str) -> (str, Optional[str]):
    """generates python test script and runs in docker"""
    script = ""
    if imports:
        script += "\n".join(f"import {imp}" for imp in imports) + "\n"
    script += f"{code}\n\n"
    script += "import json\nimport time\nimport sys\n\n"

    # serialize test cases to avoid injection attacks in generated python code
    script += "test_cases = [\n"
    for tc in test_cases:
        expected_output_repr = repr(tc.expected_output)
        script += f"    ({json.dumps(tc.input)}, {expected_output_repr}),\n"
    script += "]\n\n"

    script += f"""
results = []
for inputs, expected in test_cases:
    result_data = {{
        "inputs": inputs,
        "expected": expected,
        "result": "",
        "passed": False,
        "time": "0.0 ms"
    }}
    start_time = time.perf_counter()
    try:
        result = {function_name}(*inputs)
        duration_ms = (time.perf_counter() - start_time) * 1000

        try:
            result_str = str(result)
        except Exception as conversion_e:
            result_str = f"[Result Conversion Error: {{conversion_e}}]"

        passed = result_str == expected
        result_data["result"] = result_str
        result_data["passed"] = passed
        result_data["time"] = f"{{duration_ms:.4f}} ms"

    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        error_message = f"Error: {{type(e).__name__}}: {{e}}"
        result_data["result"] = error_message
        result_data["passed"] = False
        result_data["time"] = f"{{duration_ms:.4f}} ms"

    results.append(result_data)

for res in results:
    print(json.dumps(res))
"""
    script_path = os.path.join(temp_dir, "temp_script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    docker_command = (
        f"docker run --rm "
        f"--network none "
        f"--memory=256m --memory-swap=256m "
        f"--cpus=1.0 "
        f"-v \"{os.path.abspath(temp_dir)}\":/usr/src/app "
        f"-w /usr/src/app "
        f"python:3.10-slim "
        f"python temp_script.py"
    )
    return _run_docker_command(docker_command, timeout_seconds=15)

def run_js_code(code: str, function_name: str, imports: List[str], test_cases: List[TestCase], temp_dir: str) -> (str, Optional[str]):
    """generates javascript test script and runs in docker"""
    script = f"{code}\n\n"
    script += "const test_cases = [\n"
    for tc in test_cases:
        script += f"    {{ inputs: {json.dumps(tc.input)}, expected: {json.dumps(tc.expected_output)} }},\n"
    script += "];\n\n"

    script += f"""
const {{ performance }} = require('perf_hooks');
const results = [];

for (const testCase of test_cases) {{
    const {{ inputs, expected }} = testCase;
    let result_data = {{
        inputs: inputs,
        expected: expected,
        result: "",
        passed: false,
        time: "0.0 ms"
    }};
    let duration_ms = 0.0;

    try {{
        const start = performance.now();
        const result = {function_name}(...(Array.isArray(inputs) ? inputs : [inputs]));
        duration_ms = performance.now() - start;

        let result_str;
        let passed = false;

        if (result === undefined) {{
            result_str = "undefined";
        }} else if (result === null) {{
            result_str = "null";
        }} else {{
            try {{
                 result_str = JSON.stringify(result);
                 try {{
                     const expected_obj = JSON.parse(expected);
                     const result_obj = JSON.parse(result_str);
                     passed = JSON.stringify(expected_obj) === JSON.stringify(result_obj);
                 }} catch (e) {{
                     passed = result_str === expected;
                 }}
            }} catch (stringifyError) {{
                 try {{
                     result_str = String(result);
                     passed = result_str === expected;
                 }} catch (toStringError) {{
                     result_str = "[Result Conversion Error: " + toStringError.message + "]";
                     passed = false;
                 }}
            }}
        }}

        if (!passed && result_str !== null && typeof result_str === 'string' && !result_str.startsWith("[Result Conversion Error")) {{
             passed = result_str === expected;
        }}

        result_data.result = result_str;
        result_data.passed = passed;
        result_data.time = `${{duration_ms.toFixed(4)}} ms`;

    }} catch (e) {{
        const error_message = `Error: ${{e.name || 'UnknownError'}}: ${{e.message || String(e)}}`;
        result_data.result = error_message;
        result_data.passed = false;
        result_data.time = `${{duration_ms.toFixed(4)}} ms`;
    }}
    results.push(result_data);
}}

results.forEach(res => {{
    console.log(JSON.stringify(res));
}});
"""
    script_path = os.path.join(temp_dir, "temp_script.js")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    docker_command = (
        f"docker run --rm "
        f"--network none "
        f"--memory=256m --memory-swap=256m "
        f"--cpus=1.0 "
        f"-v \"{os.path.abspath(temp_dir)}\":/usr/src/app "
        f"-w /usr/src/app "
        f"node:18-slim "
        f"node temp_script.js"
    )
    return _run_docker_command(docker_command, timeout_seconds=15)

def run_code_in_docker(language: str, code: str, function_name: str, imports: List[str], test_cases: List[TestCase]) -> (str, Optional[str]):
    """routes to language-specific docker execution"""
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Created temporary directory: {temp_dir}")
        if language == 'python':
            return run_python_code(code, function_name, imports, test_cases, temp_dir)
        elif language == 'js':
            return run_js_code(code, function_name, imports, test_cases, temp_dir)
        elif language == 'java':
            return run_java_code(code, function_name, imports, test_cases, temp_dir)
        elif language == 'cpp':
            return run_cpp_code(code, function_name, imports, test_cases, temp_dir)
        elif language == 'go':
            return run_go_code(code, function_name, imports, test_cases, temp_dir)
        else:
            return "", f"Unsupported language '{language}' specified for Docker execution."

def run_java_code(code: str, function_name: str, imports: List[str], test_cases: List[TestCase], temp_dir: str) -> (str, Optional[str]):
    """generates java test runner with gson for json handling"""
    
    class_name_match = re.search(r'public\s+class\s+(\w+)', code)
    class_name = class_name_match.group(1) if class_name_match else "Solution"
    
    java_code = ""
    
    if imports:
        java_code += "\n".join(f"import {imp};" for imp in imports) + "\n"
    
    java_code += """
import java.util.*;
import java.io.*;
import com.google.gson.*;
import java.lang.reflect.*;

"""
    
    user_code = code.replace("public class", "class")
    java_code += user_code + "\n\n"
    
    java_code += f"""
public class TestRunner {{
    private static final Gson gson = new Gson();
    
    public static void main(String[] args) {{
        TestCase[] testCases = {{
"""
    
    # convert python types to java literals for test data
    for tc in test_cases:
        def convert_to_java_literal(item):
            if item is None:
                return "null"
            elif isinstance(item, bool):
                return "true" if item else "false"
            elif isinstance(item, str):
                return json.dumps(item)
            elif isinstance(item, (int, float)):
                return str(item)
            elif isinstance(item, list):
                if not item:
                    return "new Object[]{}"
                if all(isinstance(x, list) for x in item):
                    if all(all(isinstance(y, bool) for y in x) for x in item):
                        rows = []
                        for row in item:
                            row_str = "{" + ", ".join("true" if x else "false" for x in row) + "}"
                            rows.append(row_str)
                        return "new boolean[][]{" + ", ".join(rows) + "}"
                    elif all(all(isinstance(y, (int, float)) for y in x) for x in item):
                        rows = []
                        for row in item:
                            row_str = "{" + ", ".join(str(x) for x in row) + "}"
                            rows.append(row_str)
                        return "new int[][]{" + ", ".join(rows) + "}"
                    else:
                        rows = []
                        for row in item:
                            row_str = "{" + ", ".join(convert_to_java_literal(x) for x in row) + "}"
                            rows.append(row_str)
                        return "new Object[][]{" + ", ".join(rows) + "}"
                else:
                    if all(isinstance(x, bool) for x in item):
                        return "new boolean[]{" + ", ".join("true" if x else "false" for x in item) + "}"
                    elif all(isinstance(x, (int, float)) for x in item):
                        return "new int[]{" + ", ".join(str(x) for x in item) + "}"
                    elif all(isinstance(x, str) for x in item):
                        return "new String[]{" + ", ".join(json.dumps(x) for x in item) + "}"
                    else:
                        return "new Object[]{" + ", ".join(convert_to_java_literal(x) for x in item) + "}"
            elif isinstance(item, dict):
                return "null"
            else:
                return json.dumps(item)
        
        inputs_str = "new Object[]{" + ", ".join(convert_to_java_literal(item) for item in tc.input) + "}"
        expected_json = json.dumps(tc.expected_output)
        java_code += f'            new TestCase({inputs_str}, {expected_json}),\n'
    
    java_code += """        };
        
        for (TestCase testCase : testCases) {
            TestResult result = new TestResult();
            result.inputs = testCase.inputs;
            result.expected = testCase.expected;
            result.passed = false;
            result.time = "0.0 ms";
            
            long startTime = System.nanoTime();
            try {
"""
    
    # reflection needed since we don't know method signature at compile time
    java_code += f"""                {class_name} solution = new {class_name}();
                Object[] methodArgs = testCase.inputs.toArray();
                
                Method method = findMethod(solution.getClass(), "{function_name}", methodArgs);
                Object result_obj = method.invoke(solution, convertArgs(method, methodArgs));
                
                long duration = System.nanoTime() - startTime;
                double durationMs = duration / 1_000_000.0;
                
                String resultStr = convertResultToString(result_obj);
                result.result = resultStr;
                result.passed = resultStr.equals(testCase.expected);
                result.time = String.format("%.4f ms", durationMs);
                
            }} catch (Exception e) {{
                long duration = System.nanoTime() - startTime;
                double durationMs = duration / 1_000_000.0;
                result.result = "Error: " + e.getClass().getSimpleName() + ": " + e.getMessage();
                result.passed = false;
                result.time = String.format("%.4f ms", durationMs);
            }}
            
            System.out.println(gson.toJson(result));
        }}
    }}
    
    private static Method findMethod(Class<?> clazz, String methodName, Object[] args) throws NoSuchMethodException {{
        Method[] methods = clazz.getDeclaredMethods();
        Method bestMatch = null;
        
        for (Method method : methods) {{
            if (method.getName().equals(methodName) && method.getParameterCount() == args.length) {{
                Class<?>[] paramTypes = method.getParameterTypes();
                boolean canHandle = true;
                
                for (int i = 0; i < args.length; i++) {{
                    if (args[i] != null && !isCompatible(args[i], paramTypes[i])) {{
                        canHandle = false;
                        break;
                    }}
                }}
                
                if (canHandle) {{
                    bestMatch = method;
                    break;
                }}
            }}
        }}
        
        if (bestMatch != null) {{
            return bestMatch;
        }}
        
        throw new NoSuchMethodException("Method " + methodName + " not found with compatible parameters");
    }}
    
    private static boolean isCompatible(Object arg, Class<?> targetType) {{
        if (arg == null) return true;
        
        if (targetType.isAssignableFrom(arg.getClass())) {{
            return true;
        }}
        
        if (List.class.isAssignableFrom(targetType) && arg instanceof List) {{
            return true;
        }}
        
        if (List.class.isAssignableFrom(targetType) && arg.getClass().isArray()) {{
            return true;
        }}
        
        if (targetType.isPrimitive()) {{
            if ((targetType == int.class && arg instanceof Integer) ||
                (targetType == boolean.class && arg instanceof Boolean) ||
                (targetType == double.class && arg instanceof Double) ||
                (targetType == float.class && arg instanceof Float) ||
                (targetType == long.class && arg instanceof Long) ||
                (targetType == byte.class && arg instanceof Byte) ||
                (targetType == short.class && arg instanceof Short) ||
                (targetType == char.class && arg instanceof Character)) {{
                return true;
            }}
        }}
        
        if (arg instanceof Number) {{
            if (targetType == int.class || targetType == Integer.class ||
                targetType == double.class || targetType == Double.class ||
                targetType == float.class || targetType == Float.class ||
                targetType == long.class || targetType == Long.class ||
                targetType == byte.class || targetType == Byte.class ||
                targetType == short.class || targetType == Short.class) {{
                return true;
            }}
        }}
        
        return false;
    }}
    
    private static Object[] convertArgs(Method method, Object[] args) {{
        Class<?>[] paramTypes = method.getParameterTypes();
        Object[] convertedArgs = new Object[args.length];
        
        for (int i = 0; i < args.length; i++) {{
            convertedArgs[i] = convertArgument(args[i], paramTypes[i]);
        }}
        
        return convertedArgs;
    }}
    
    private static Object convertArgument(Object arg, Class<?> targetType) {{
        if (arg == null) {{
            if (targetType.isPrimitive()) {{
                if (targetType == boolean.class) return false;
                if (targetType == int.class) return 0;
                if (targetType == double.class) return 0.0;
                if (targetType == float.class) return 0.0f;
                if (targetType == long.class) return 0L;
                if (targetType == byte.class) return (byte) 0;
                if (targetType == short.class) return (short) 0;
                if (targetType == char.class) return '\\0';
            }}
            return null;
        }}
        
        if (targetType.isAssignableFrom(arg.getClass())) return arg;
        
        if (List.class.isAssignableFrom(targetType)) {{
            if (arg instanceof List) {{
                List<?> sourceList = (List<?>) arg;
                List<Object> targetList = new ArrayList<>();
                for (Object item : sourceList) {{
                    if (item instanceof List) {{
                        targetList.add(new ArrayList<>((List<?>) item));
                    }} else {{
                        targetList.add(item);
                    }}
                }}
                return targetList;
            }} else if (arg.getClass().isArray()) {{
                List<Object> targetList = new ArrayList<>();
                int length = Array.getLength(arg);
                for (int i = 0; i < length; i++) {{
                    Object element = Array.get(arg, i);
                    if (element != null && element.getClass().isArray()) {{
                        List<Object> nestedList = new ArrayList<>();
                        int nestedLength = Array.getLength(element);
                        for (int j = 0; j < nestedLength; j++) {{
                            nestedList.add(Array.get(element, j));
                        }}
                        targetList.add(nestedList);
                    }} else {{
                        targetList.add(element);
                    }}
                }}
                return targetList;
            }}
        }}
        
        if (targetType.isArray()) {{
            if (arg instanceof List) {{
                List<?> list = (List<?>) arg;
                Class<?> componentType = targetType.getComponentType();
                Object array = Array.newInstance(componentType, list.size());
                for (int i = 0; i < list.size(); i++) {{
                    Array.set(array, i, convertArgument(list.get(i), componentType));
                }}
                return array;
            }}
        }}
        
        if (Set.class.isAssignableFrom(targetType)) {{
            if (arg instanceof List) {{
                return new HashSet<>((List<?>) arg);
            }} else if (arg.getClass().isArray()) {{
                Set<Object> targetSet = new HashSet<>();
                int length = Array.getLength(arg);
                for (int i = 0; i < length; i++) {{
                    targetSet.add(Array.get(arg, i));
                }}
                return targetSet;
            }}
        }}
        
        if (Map.class.isAssignableFrom(targetType)) {{
            return new HashMap<>();
        }}
        
        if (Queue.class.isAssignableFrom(targetType)) {{
            if (arg instanceof List) {{
                return new LinkedList<>((List<?>) arg);
            }}
        }}
        
        if (Stack.class.isAssignableFrom(targetType)) {{
            Stack<Object> stack = new Stack<>();
            if (arg instanceof List) {{
                for (Object item : (List<?>) arg) {{
                    stack.push(item);
                }}
            }}
            return stack;
        }}
        
        if (arg instanceof Number) {{
            Number num = (Number) arg;
            if (targetType == int.class || targetType == Integer.class) return num.intValue();
            if (targetType == long.class || targetType == Long.class) return num.longValue();
            if (targetType == double.class || targetType == Double.class) return num.doubleValue();
            if (targetType == float.class || targetType == Float.class) return num.floatValue();
            if (targetType == byte.class || targetType == Byte.class) return num.byteValue();
            if (targetType == short.class || targetType == Short.class) return num.shortValue();
        }}
        
        if (targetType == String.class && arg != null) return arg.toString();
        
        if (targetType == boolean.class || targetType == Boolean.class) {{
            if (arg instanceof Boolean) return arg;
            if (arg instanceof String) return Boolean.parseBoolean((String) arg);
            if (arg instanceof Number) return ((Number) arg).intValue() != 0;
        }}
        
        if (targetType == char.class || targetType == Character.class) {{
            if (arg instanceof Character) return arg;
            if (arg instanceof String) {{
                String str = (String) arg;
                return str.length() > 0 ? str.charAt(0) : '\\0';
            }}
            if (arg instanceof Number) return (char) ((Number) arg).intValue();
        }}
        
        return arg;
    }}
    
    private static String convertResultToString(Object result) {{
        if (result == null) return "null";
        
        if (result.getClass().isArray()) {{
            Class<?> componentType = result.getClass().getComponentType();
            if (componentType.isPrimitive()) {{
                if (componentType == int.class) return Arrays.toString((int[]) result);
                if (componentType == double.class) return Arrays.toString((double[]) result);
                if (componentType == boolean.class) return Arrays.toString((boolean[]) result);
                if (componentType == long.class) return Arrays.toString((long[]) result);
                if (componentType == float.class) return Arrays.toString((float[]) result);
                if (componentType == char.class) return Arrays.toString((char[]) result);
                if (componentType == byte.class) return Arrays.toString((byte[]) result);
                if (componentType == short.class) return Arrays.toString((short[]) result);
            }}
            return Arrays.deepToString((Object[]) result);
        }}
        
        if (result instanceof List) {{
            return result.toString();
        }}
        
        if (result instanceof Set) {{
            return result.toString();
        }}
        
        if (result instanceof Map) {{
            return result.toString();
        }}
        
        return result.toString();
    }}
    
    static class TestCase {{
        List<Object> inputs;
        String expected;
        
        TestCase(Object[] inputs, String expected) {{
            this.inputs = Arrays.asList(inputs);
            this.expected = expected;
        }}
    }}
    
    static class TestResult {{
        List<Object> inputs;
        String expected;
        String result;
        boolean passed;
        String time;
    }}
}}
"""
    
    java_file_path = os.path.join(temp_dir, "TestRunner.java")
    with open(java_file_path, "w", encoding="utf-8") as f:
        f.write(java_code)
    
    # hide apt-get output to prevent json parsing errors
    docker_command = (
        f"docker run --rm "
        f"--memory=512m --memory-swap=512m "
        f"--cpus=1.0 "
        f"-v \"{os.path.abspath(temp_dir)}\":/usr/src/app "
        f"-w /usr/src/app "
        f"openjdk:11-jdk-slim "
        f"sh -c 'apt-get update >/dev/null 2>&1 && apt-get install -y wget >/dev/null 2>&1 && "
        f"wget -q https://repo1.maven.org/maven2/com/google/code/gson/gson/2.8.9/gson-2.8.9.jar -O gson.jar && "
        f"javac -cp gson.jar TestRunner.java && "
        f"java -cp .:gson.jar TestRunner'"
    )
    
    return _run_docker_command(docker_command, timeout_seconds=30)

def run_cpp_code(code: str, function_name: str, imports: List[str], test_cases: List[TestCase], temp_dir: str) -> (str, Optional[str]):
    """generates c++ test runner with manual json formatting"""
    
    cpp_code = ""
    
    cpp_code += "#include <iostream>\n"
    cpp_code += "#include <vector>\n"
    cpp_code += "#include <string>\n"
    cpp_code += "#include <map>\n"
    cpp_code += "#include <set>\n"
    cpp_code += "#include <algorithm>\n"
    cpp_code += "#include <chrono>\n"
    cpp_code += "#include <sstream>\n"
    cpp_code += "#include <iomanip>\n"
    cpp_code += "#include <type_traits>\n"
    
    if imports:
        for imp in imports:
            cpp_code += f"#include <{imp}>\n"
    
    cpp_code += "\nusing namespace std;\nusing namespace std::chrono;\n\n"
    
    # c++ doesn't have native json so we build a simple result structure
    cpp_code += """
struct TestResult {
    string inputs;
    string expected;
    string result;
    bool passed;
    string time;
    
    string toJson() const {
        stringstream ss;
        ss << "{\\"inputs\\":" << inputs << ",\\"expected\\":\\"" << expected 
           << "\\",\\"result\\":\\"" << result << "\\",\\"passed\\":" 
           << (passed ? "true" : "false") << ",\\"time\\":\\"" << time << "\\"}";
        return ss.str();
    }
};

template<typename T>
string vectorToString(const vector<T>& vec) {
    if (vec.empty()) return "[]";
    stringstream ss;
    ss << "[";
    for (size_t i = 0; i < vec.size(); ++i) {
        if (i > 0) ss << ", ";
        if constexpr (is_same_v<T, string>) {
            ss << vec[i];
        } else {
            ss << vec[i];
        }
    }
    ss << "]";
    return ss.str();
}

template<typename T>
string vector2DToString(const vector<vector<T>>& vec) {
    if (vec.empty()) return "[]";
    stringstream ss;
    ss << "[";
    for (size_t i = 0; i < vec.size(); ++i) {
        if (i > 0) ss << ", ";
        ss << vectorToString(vec[i]);
    }
    ss << "]";
    return ss.str();
}

template<typename T>
string resultToString(const T& result) {
    if constexpr (is_same_v<T, string>) {
        return result;
    } else if constexpr (is_same_v<T, vector<string>>) {
        return vectorToString(result);
    } else if constexpr (is_same_v<T, vector<int>>) {
        return vectorToString(result);
    } else if constexpr (is_same_v<T, vector<double>>) {
        return vectorToString(result);
    } else if constexpr (is_same_v<T, vector<bool>>) {
        return vectorToString(result);
    } else if constexpr (is_same_v<T, vector<vector<int>>>) {
        return vector2DToString(result);
    } else if constexpr (is_same_v<T, vector<vector<string>>>) {
        return vector2DToString(result);
    } else if constexpr (is_arithmetic_v<T>) {
        return to_string(result);
    } else {
        stringstream ss;
        ss << result;
        return ss.str();
    }
}

"""
    
    cpp_code += code + "\n\n"
    
    cpp_code += "int main() {\n"
    cpp_code += "    vector<TestResult> results;\n\n"
    
    for i, tc in enumerate(test_cases):
        cpp_code += f"    // test case {i + 1}\n"
        cpp_code += "    {\n"
        cpp_code += "        TestResult result;\n"
        
        cpp_code += f"        result.inputs = {json.dumps(str(tc.input))};\n"
        cpp_code += f"        result.expected = {json.dumps(tc.expected_output)};\n"
        cpp_code += "        result.passed = false;\n"
        cpp_code += "        result.time = \"0.0 ms\";\n\n"
        
        for j, inp in enumerate(tc.input):
            param_decl = generate_cpp_param_declaration(f"param{j}", inp)
            cpp_code += f"        {param_decl}\n"
        
        cpp_code += "        auto start = high_resolution_clock::now();\n"
        cpp_code += "        try {\n"
        
        function_call = generate_cpp_function_call(function_name, tc.input)
        cpp_code += f"            auto functionResult = {function_call};\n"
        
        cpp_code += "            auto end = high_resolution_clock::now();\n"
        cpp_code += "            auto duration = duration_cast<microseconds>(end - start);\n"
        cpp_code += "            double durationMs = duration.count() / 1000.0;\n\n"
        
        cpp_code += "            string resultStr = resultToString(functionResult);\n"
        cpp_code += "            result.result = resultStr;\n"
        cpp_code += "            result.passed = (resultStr == result.expected);\n"
        cpp_code += "            \n"
        cpp_code += "            stringstream timeStream;\n"
        cpp_code += "            timeStream << fixed << setprecision(4) << durationMs << \" ms\";\n"
        cpp_code += "            result.time = timeStream.str();\n"
        
        cpp_code += "        } catch (const exception& e) {\n"
        cpp_code += "            auto end = high_resolution_clock::now();\n"
        cpp_code += "            auto duration = duration_cast<microseconds>(end - start);\n"
        cpp_code += "            double durationMs = duration.count() / 1000.0;\n"
        cpp_code += "            \n"
        cpp_code += "            result.result = string(\"Error: \") + e.what();\n"
        cpp_code += "            result.passed = false;\n"
        cpp_code += "            \n"
        cpp_code += "            stringstream timeStream;\n"
        cpp_code += "            timeStream << fixed << setprecision(4) << durationMs << \" ms\";\n"
        cpp_code += "            result.time = timeStream.str();\n"
        cpp_code += "        }\n"
        cpp_code += "        \n"
        cpp_code += "        results.push_back(result);\n"
        cpp_code += "    }\n\n"
    
    cpp_code += "    for (const auto& result : results) {\n"
    cpp_code += "        cout << result.toJson() << endl;\n"
    cpp_code += "    }\n"
    cpp_code += "    \n"
    cpp_code += "    return 0;\n"
    cpp_code += "}\n"
    
    cpp_file_path = os.path.join(temp_dir, "main.cpp")
    with open(cpp_file_path, "w", encoding="utf-8") as f:
        f.write(cpp_code)
    
    docker_command = (
        f"docker run --rm "
        f"--memory=512m --memory-swap=512m "
        f"--cpus=1.0 "
        f"-v \"{os.path.abspath(temp_dir)}\":/usr/src/app "
        f"-w /usr/src/app "
        f"gcc:latest "
        f"bash -c 'g++ -std=c++17 -O2 -o main main.cpp && ./main'"
    )
    
    return _run_docker_command(docker_command, timeout_seconds=30)

def generate_cpp_param_declaration(var_name, inp):
    """convert python value to c++ variable declaration"""
    if isinstance(inp, list):
        if all(isinstance(x, list) for x in inp):
            return f"vector<vector<int>> {var_name} = {format_cpp_2d_vector(inp)};"
        else:
            if all(isinstance(x, str) for x in inp):
                formatted_strings = [f'"{x}"' for x in inp]
                return f"vector<string> {var_name} = {{{', '.join(formatted_strings)}}};"
            else:
                return f"vector<int> {var_name} = {format_cpp_vector(inp)};"
    elif isinstance(inp, str):
        return f'string {var_name} = "{inp}";'
    elif isinstance(inp, bool):
        return f"bool {var_name} = {'true' if inp else 'false'};"
    elif isinstance(inp, int):
        return f"int {var_name} = {inp};"
    elif isinstance(inp, float):
        return f"double {var_name} = {inp};"
    else:
        return f"auto {var_name} = {inp};"

def format_cpp_vector(vec):
    """format python list as c++ vector initializer"""
    if not vec:
        return "{}"
    return "{" + ", ".join(str(x) for x in vec) + "}"

def format_cpp_2d_vector(vec):
    """format python 2d list as c++ 2d vector initializer"""
    if not vec:
        return "{}"
    formatted_rows = []
    for row in vec:
        formatted_rows.append(format_cpp_vector(row))
    return "{" + ", ".join(formatted_rows) + "}"

def generate_cpp_function_call(function_name, inputs):
    """generate c++ function call with appropriate parameters"""
    params = []
    for i in range(len(inputs)):
        params.append(f"param{i}")
    return f"{function_name}({', '.join(params)})"

def run_go_code(code: str, function_name: str, imports: List[str], test_cases: List[TestCase], temp_dir: str) -> (str, Optional[str]):
    """generates go test runner with json marshaling"""
    
    go_code = ""
    
    go_code += "package main\n\n"
    
    go_code += "import (\n"
    go_code += "\t\"encoding/json\"\n"
    go_code += "\t\"fmt\"\n"
    go_code += "\t\"time\"\n"
    go_code += "\t\"strconv\"\n"
    go_code += "\t\"strings\"\n"
    go_code += "\t\"reflect\"\n"
    
    if imports:
        for imp in imports:
            go_code += f"\t\"{imp}\"\n"
    
    go_code += ")\n\n"
    
    go_code += """type TestResult struct {
    Inputs   interface{} `json:"inputs"`
    Expected string      `json:"expected"`
    Result   string      `json:"result"`
    Passed   bool        `json:"passed"`
    Time     string      `json:"time"`
}

func interfaceToString(v interface{}) string {
    if v == nil {
        return "null"
    }
    
    switch val := v.(type) {
    case string:
        return val
    case int, int32, int64, float32, float64:
        return fmt.Sprintf("%v", val)
    case bool:
        if val {
            return "true"
        }
        return "false"
    case []interface{}:
        if len(val) == 0 {
            return "[]"
        }
        var parts []string
        for _, item := range val {
            parts = append(parts, interfaceToString(item))
        }
        return "[" + strings.Join(parts, ", ") + "]"
    case []int:
        if len(val) == 0 {
            return "[]"
        }
        var parts []string
        for _, item := range val {
            parts = append(parts, strconv.Itoa(item))
        }
        return "[" + strings.Join(parts, ", ") + "]"
    case []string:
        if len(val) == 0 {
            return "[]"
        }
        return "[" + strings.Join(val, ", ") + "]"
    case [][]int:
        if len(val) == 0 {
            return "[]"
        }
        var parts []string
        for _, row := range val {
            parts = append(parts, interfaceToString(row))
        }
        return "[" + strings.Join(parts, ", ") + "]"
    default:
        v_val := reflect.ValueOf(v)
        if v_val.Kind() == reflect.Slice {
            if v_val.Len() == 0 {
                return "[]"
            }
            var parts []string
            for i := 0; i < v_val.Len(); i++ {
                parts = append(parts, interfaceToString(v_val.Index(i).Interface()))
            }
            return "[" + strings.Join(parts, ", ") + "]"
        }
        return fmt.Sprintf("%v", v)
    }
}

"""
    
    go_code += code + "\n\n"
    
    go_code += "func main() {\n"
    go_code += "\tvar results []TestResult\n\n"
    
    for i, tc in enumerate(test_cases):
        go_code += f"\t// test case {i + 1}\n"
        go_code += "\t{\n"
        go_code += "\t\tresult := TestResult{}\n"
        
        inputs_json = json.dumps(tc.input)
        go_code += f"\t\tvar inputs interface{{}}\n"
        go_code += f"\t\tjson.Unmarshal([]byte(`{inputs_json}`), &inputs)\n"
        go_code += f"\t\tresult.Inputs = inputs\n"
        go_code += f"\t\tresult.Expected = {json.dumps(tc.expected_output)}\n"
        go_code += "\t\tresult.Passed = false\n"
        go_code += "\t\tresult.Time = \"0.0 ms\"\n\n"
        
        go_code += "\t\tstart := time.Now()\n"
        go_code += "\t\tvar functionResult interface{}\n"
        go_code += "\t\tvar err error\n\n"
        
        go_code += generate_go_function_call(function_name, tc.input, i)
        
        go_code += "\t\tduration := time.Since(start)\n"
        go_code += "\t\tdurationMs := float64(duration.Nanoseconds()) / 1000000.0\n\n"
        
        go_code += "\t\tif err != nil {\n"
        go_code += "\t\t\tresult.Result = fmt.Sprintf(\"Error: %v\", err)\n"
        go_code += "\t\t\tresult.Passed = false\n"
        go_code += "\t\t} else {\n"
        go_code += "\t\t\tresultStr := interfaceToString(functionResult)\n"
        go_code += "\t\t\tresult.Result = resultStr\n"
        go_code += "\t\t\tresult.Passed = (resultStr == result.Expected)\n"
        go_code += "\t\t}\n\n"
        
        go_code += "\t\tresult.Time = fmt.Sprintf(\"%.4f ms\", durationMs)\n"
        go_code += "\t\tresults = append(results, result)\n"
        go_code += "\t}\n\n"
    
    go_code += "\tfor _, result := range results {\n"
    go_code += "\t\tjsonBytes, _ := json.Marshal(result)\n"
    go_code += "\t\tfmt.Println(string(jsonBytes))\n"
    go_code += "\t}\n"
    go_code += "}\n"
    
    go_file_path = os.path.join(temp_dir, "main.go")
    with open(go_file_path, "w", encoding="utf-8") as f:
        f.write(go_code)
    
    docker_command = (
        f"docker run --rm "
        f"--memory=512m --memory-swap=512m "
        f"--cpus=1.0 "
        f"-v \"{os.path.abspath(temp_dir)}\":/usr/src/app "
        f"-w /usr/src/app "
        f"golang:1.21-alpine "
        f"sh -c 'rm -f go.mod go.sum && go mod init main && go run main.go'"
    )
    
    return _run_docker_command(docker_command, timeout_seconds=30)

def generate_go_function_call(function_name, inputs, test_index):
    """generate go function call with proper parameter handling"""
    call_code = ""
    
    call_code += "\t\t// parse and call function\n"
    
    if len(inputs) == 0:
        call_code += f"\t\tfunctionResult, err = {function_name}()\n"
    else:
        for i, inp in enumerate(inputs):
            call_code += generate_go_param_parsing(f"param{i}", inp, i)
        
        params = [f"param{i}" for i in range(len(inputs))]
        call_code += f"\t\tif err == nil {{\n"
        call_code += f"\t\t\tfunctionResult = {function_name}({', '.join(params)})\n"
        call_code += "\t\t}\n"
    
    return call_code

def generate_go_param_parsing(var_name, inp, index):
    """generate go parameter parsing code"""
    if isinstance(inp, list):
        if all(isinstance(x, list) for x in inp):
            return f"\t\t{var_name} := {format_go_2d_slice(inp)}\n"
        else:
            if all(isinstance(x, str) for x in inp):
                formatted_strings = [f'"{x}"' for x in inp]
                return f"\t\t{var_name} := []string{{{', '.join(formatted_strings)}}}\n"
            elif all(isinstance(x, (int, float)) for x in inp):
                return f"\t\t{var_name} := []int{format_go_slice(inp)}\n"
            else:
                return f"\t\t{var_name} := []interface{{{format_go_interface_slice(inp)}}}\n"
    elif isinstance(inp, str):
        return f'\t\t{var_name} := "{inp}"\n'
    elif isinstance(inp, bool):
        return f"\t\t{var_name} := {'true' if inp else 'false'}\n"
    elif isinstance(inp, int):
        return f"\t\t{var_name} := {inp}\n"
    elif isinstance(inp, float):
        return f"\t\t{var_name} := {inp}\n"
    else:
        return f"\t\t{var_name} := {inp}\n"

def format_go_slice(slice_data):
    """format python list as go slice initializer"""
    if not slice_data:
        return "{}"
    return "{" + ", ".join(str(x) for x in slice_data) + "}"

def format_go_2d_slice(slice_data):
    """format python 2d list as go 2d slice initializer"""
    if not slice_data:
        return "[][]int{}"
    formatted_rows = []
    for row in slice_data:
        formatted_rows.append(format_go_slice(row))
    return "[][]int{" + ", ".join(formatted_rows) + "}"

def format_go_interface_slice(slice_data):
    """format python list as go interface slice"""
    if not slice_data:
        return "{}"
    formatted_items = []
    for item in slice_data:
        if isinstance(item, str):
            formatted_items.append(f'"{item}"')
        elif isinstance(item, bool):
            formatted_items.append('true' if item else 'false')
        else:
            formatted_items.append(str(item))
    return "{" + ", ".join(formatted_items) + "}"

@celery.task(name='code_execution_app.execute_code_task', bind=True, max_retries=2, default_retry_delay=5)
def execute_code_task(self, data: Dict[str, Any], execution_id: str):
    """celery task that executes code in docker and sends callback"""
    language = data['language']
    code = data['code']
    function_name = data['function_name']
    imports = data['imports']
    try:
        test_cases = [TestCase(**tc) for tc in data['test_cases']]
    except Exception as pydantic_err:
         print(f"[{execution_id}] Error: Malformed test case data received: {pydantic_err}")
         payload = CallbackPayload(id=execution_id, results=[], all_passed=False, error="Invalid test case format", error_details=str(pydantic_err))
         _send_callback(data['callback_url'], payload.model_dump(), execution_id, self)
         return payload.model_dump()

    callback_url = data['callback_url']

    results: List[ExecutionResult] = []
    all_passed = True
    overall_error: Optional[str] = None
    overall_error_details: Optional[str] = None

    try:
        stdout, execution_error = run_code_in_docker(language, code, function_name, imports, test_cases)

        if execution_error:
            print(f"[{execution_id}] Execution Error: {execution_error}")
            overall_error = "Execution environment error"
            overall_error_details = execution_error
            all_passed = False
            for tc in test_cases:
                results.append(ExecutionResult(
                    input=tc.input, expected_output=tc.expected_output,
                    actual_output="Execution Failed", passed=False, time="0.0 ms"
                ))

        elif not stdout.strip():
             print(f"[{execution_id}] Warning: No output received from successful execution.")
             overall_error = "No output received"
             overall_error_details = "The code executed successfully but produced no standard output."
             all_passed = False
             for tc in test_cases:
                 results.append(ExecutionResult(
                     input=tc.input, expected_output=tc.expected_output,
                     actual_output="No Output", passed=False, time="0.0 ms"
                 ))

        else:
            # parse json output line by line
            output_lines = stdout.strip().split('\n')
            parsed_results_count = 0
            json_parsing_errors = []

            for line_num, line in enumerate(output_lines):
                line = line.strip()
                if not line: continue

                try:
                    res_json = json.loads(line)
                    result = ExecutionResult(
                        input=res_json.get('inputs', res_json.get('input', [])),
                        expected_output=res_json.get('expected', ''),
                        actual_output=res_json.get('result', ''),
                        passed=bool(res_json.get('passed', False)),
                        time=str(res_json.get('time', '0.0 ms'))
                    )
                    results.append(result)
                    if not result.passed:
                        all_passed = False
                    parsed_results_count += 1
                except json.JSONDecodeError as json_e:
                    msg = f"Failed to decode JSON on line {line_num + 1}: '{line}'. Error: {json_e}"
                    print(f"[{execution_id}] {msg}")
                    json_parsing_errors.append(msg)
                    all_passed = False
                except Exception as parse_e:
                     msg = f"Error processing result on line {line_num + 1}: '{line}'. Error: {type(parse_e).__name__}: {parse_e}"
                     print(f"[{execution_id}] {msg}")
                     json_parsing_errors.append(msg)
                     all_passed = False

            if json_parsing_errors:
                 overall_error = "Result parsing error"
                 overall_error_details = "\n".join(json_parsing_errors)

            if parsed_results_count != len(test_cases) and not overall_error:
                overall_error = "Result count mismatch"
                overall_error_details = f"Expected {len(test_cases)} results, got {parsed_results_count}."
                all_passed = False
                while len(results) < len(test_cases):
                    missing_idx = len(results)
                    results.append(ExecutionResult(
                        input=test_cases[missing_idx].input if missing_idx < len(test_cases) else ["Unknown"],
                        expected_output=test_cases[missing_idx].expected_output if missing_idx < len(test_cases) else "Unknown",
                        actual_output="Missing Result", passed=False, time="0.0 ms"
                    ))

    except Exception as task_err:
        print(f"[{execution_id}] Internal Task Error: {type(task_err).__name__}: {task_err}")
        overall_error = "Internal task error"
        overall_error_details = f"{type(task_err).__name__}: {task_err}"
        all_passed = False
        if not results:
            for tc in test_cases:
                results.append(ExecutionResult(
                    input=tc.input, expected_output=tc.expected_output,
                    actual_output="Internal Error", passed=False, time="0.0 ms"
                ))

    payload = CallbackPayload(
        id=execution_id,
        results=results,
        all_passed=all_passed and (overall_error is None),
        error=overall_error,
        error_details=overall_error_details
    )

    # send http callback with celery retry logic for reliability
    _send_callback(callback_url, payload.model_dump(), execution_id, self)

    return payload.model_dump()

def _send_callback(callback_url: str, payload: Dict[str, Any], execution_id: str, task_instance: Celery.Task):
    """send http callback with celery retry logic for reliability"""
    try:
        print(f"[{execution_id}] Sending callback to {callback_url}")
        response = requests.post(callback_url, json=payload, timeout=20)
        response.raise_for_status()
        print(f"[{execution_id}] Callback successful (Status: {response.status_code})")
    except requests.exceptions.RequestException as e:
        print(f"[{execution_id}] Error sending callback: {e}")
        try:
            retry_num = task_instance.request.retries + 1
            print(f"[{execution_id}] Retrying callback (Attempt {retry_num}/{task_instance.max_retries + 1})...")
            raise task_instance.retry(exc=e, countdown=10 * retry_num)
        except task_instance.MaxRetriesExceededError:
            print(f"[{execution_id}] Max retries exceeded. Callback failed permanently for {callback_url}.")
    except Exception as e_generic:
         print(f"[{execution_id}] Unexpected error during callback sending: {type(e_generic).__name__}: {e_generic}")

@app.post("/execute", status_code=202, response_model=Dict[str, str])
async def execute_code_endpoint(request: CodeExecutionRequest):
    """accepts code execution requests and queues them via celery"""
    try:
        validate_input(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    execution_id = str(uuid.uuid4())
    request_data = request.model_dump()

    execute_code_task.apply_async(args=[request_data, execution_id], queue='code_execution')

    print(f"[{execution_id}] Task queued for language '{request.language}'")
    return {"message": "Code execution task accepted", "id": execution_id}

if __name__ == '__main__':
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting FastAPI server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)