#!/usr/bin/env python3
"""
Generate cURL commands for findMedianSortedArrays in Java, C++, and Go
with clean implementations (no hardcoded parameters)
"""

import json

def generate_java_curl():
    """Generate cURL for Java findMedianSortedArrays"""
    
    java_code = """
import java.util.*;

class Solution {
    public double findMedianSortedArrays(int[] nums1, int[] nums2) {
        if (nums1.length > nums2.length) {
            return findMedianSortedArrays(nums2, nums1);
        }
        
        int m = nums1.length;
        int n = nums2.length;
        int low = 0, high = m;
        
        while (low <= high) {
            int cut1 = (low + high) / 2;
            int cut2 = (m + n + 1) / 2 - cut1;
            
            int left1 = (cut1 == 0) ? Integer.MIN_VALUE : nums1[cut1 - 1];
            int left2 = (cut2 == 0) ? Integer.MIN_VALUE : nums2[cut2 - 1];
            
            int right1 = (cut1 == m) ? Integer.MAX_VALUE : nums1[cut1];
            int right2 = (cut2 == n) ? Integer.MAX_VALUE : nums2[cut2];
            
            if (left1 <= right2 && left2 <= right1) {
                if ((m + n) % 2 == 0) {
                    return (Math.max(left1, left2) + Math.min(right1, right2)) / 2.0;
                } else {
                    return Math.max(left1, left2);
                }
            } else if (left1 > right2) {
                high = cut1 - 1;
            } else {
                low = cut1 + 1;
            }
        }
        
        return 1.0;
    }
}
"""
    
    request_data = {
        "language": "java",
        "code": java_code,
        "function_name": "findMedianSortedArrays",
        "imports": [],
        "test_cases": [
            {
                "input": [[1, 3], [2]],
                "expected_output": "2.0"
            },
            {
                "input": [[1, 2], [3, 4]],
                "expected_output": "2.5"
            },
            {
                "input": [[0, 0], [0, 0]],
                "expected_output": "0.0"
            },
            {
                "input": [[1, 3, 8], [7, 9, 10, 11]],
                "expected_output": "8.0"
            }
        ],
        "callback_url": "http://localhost:5001/callback"
    }
    
    return request_data

def generate_cpp_curl():
    """Generate cURL for C++ findMedianSortedArrays"""
    
    cpp_code = """
#include <algorithm>
#include <climits>

double findMedianSortedArrays(vector<int> nums1, vector<int> nums2) {
    if (nums1.size() > nums2.size()) {
        return findMedianSortedArrays(nums2, nums1);
    }
    
    int m = nums1.size();
    int n = nums2.size();
    int low = 0, high = m;
    
    while (low <= high) {
        int cut1 = (low + high) / 2;
        int cut2 = (m + n + 1) / 2 - cut1;
        
        int left1 = (cut1 == 0) ? INT_MIN : nums1[cut1 - 1];
        int left2 = (cut2 == 0) ? INT_MIN : nums2[cut2 - 1];
        
        int right1 = (cut1 == m) ? INT_MAX : nums1[cut1];
        int right2 = (cut2 == n) ? INT_MAX : nums2[cut2];
        
        if (left1 <= right2 && left2 <= right1) {
            if ((m + n) % 2 == 0) {
                return (max(left1, left2) + min(right1, right2)) / 2.0;
            } else {
                return max(left1, left2);
            }
        } else if (left1 > right2) {
            high = cut1 - 1;
        } else {
            low = cut1 + 1;
        }
    }
    
    return 1.0;
}
"""
    
    request_data = {
        "language": "cpp",
        "code": cpp_code,
        "function_name": "findMedianSortedArrays",
        "imports": [],
        "test_cases": [
            {
                "input": [[1, 3], [2]],
                "expected_output": "2.000000"
            },
            {
                "input": [[1, 2], [3, 4]],
                "expected_output": "2.500000"
            },
            {
                "input": [[0, 0], [0, 0]],
                "expected_output": "0.000000"
            },
            {
                "input": [[1, 3, 8], [7, 9, 10, 11]],
                "expected_output": "8.000000"
            }
        ],
        "callback_url": "http://localhost:5001/callback"
    }
    
    return request_data

def generate_go_curl():
    """Generate cURL for Go findMedianSortedArrays"""
    
    go_code = """
func findMedianSortedArrays(nums1 []int, nums2 []int) float64 {
    if len(nums1) > len(nums2) {
        return findMedianSortedArrays(nums2, nums1)
    }
    
    m := len(nums1)
    n := len(nums2)
    low := 0
    high := m
    
    for low <= high {
        cut1 := (low + high) / 2
        cut2 := (m + n + 1) / 2 - cut1
        
        var left1, left2, right1, right2 int
        
        if cut1 == 0 {
            left1 = -2147483648
        } else {
            left1 = nums1[cut1-1]
        }
        
        if cut2 == 0 {
            left2 = -2147483648
        } else {
            left2 = nums2[cut2-1]
        }
        
        if cut1 == m {
            right1 = 2147483647
        } else {
            right1 = nums1[cut1]
        }
        
        if cut2 == n {
            right2 = 2147483647
        } else {
            right2 = nums2[cut2]
        }
        
        if left1 <= right2 && left2 <= right1 {
            if (m + n) % 2 == 0 {
                return float64(max(left1, left2) + min(right1, right2)) / 2.0
            } else {
                return float64(max(left1, left2))
            }
        } else if left1 > right2 {
            high = cut1 - 1
        } else {
            low = cut1 + 1
        }
    }
    
    return 1.0
}

func max(a, b int) int {
    if a > b {
        return a
    }
    return b
}

func min(a, b int) int {
    if a < b {
        return a
    }
    return b
}
"""
    
    request_data = {
        "language": "go",
        "code": go_code,
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
                "input": [[1, 3, 8], [7, 9, 10, 11]],
                "expected_output": "8"
            }
        ],
        "callback_url": "http://localhost:5001/callback"
    }
    
    return request_data

def print_curl_command(request_data, language_name, server_url="http://localhost:8000"):
    """Print cURL command for a given request"""
    
    print(f"🔥 {language_name.upper()}: findMedianSortedArrays")
    print("=" * 80)
    
    json_data = json.dumps(request_data, indent=2)
    escaped_json = json_data.replace('"', '\\"').replace('\n', '\\n').replace('\r', '')
    
    print("curl -X POST \\")
    print(f'  "{server_url}/execute" \\')
    print('  -H "Content-Type: application/json" \\')
    print(f'  -d "{escaped_json}"')
    print()

def main():
    """Generate all cURL commands"""
    
    print("🚀 FINDMEDIANSORTEDARRAYS - CURL COMMANDS")
    print("LeetCode Hard Problem #4 - Binary Search Solution")
    print("Time Complexity: O(log(min(m,n))) | Space: O(1)")
    print("=" * 80)
    print()
    
    # Generate Java cURL
    java_data = generate_java_curl()
    print_curl_command(java_data, "Java")
    
    # Generate C++ cURL
    cpp_data = generate_cpp_curl()
    print_curl_command(cpp_data, "C++")
    
    # Generate Go cURL
    go_data = generate_go_curl()
    print_curl_command(go_data, "Go")
    
    print("💡 USAGE INSTRUCTIONS:")
    print("1. Start callback receiver: python callback_receiver.py")
    print("2. Start the execution engine: python run_server.py")
    print("3. Run any of the cURL commands above")
    print("4. Check http://localhost:5001/callback for results")
    print()
    print("🎯 CALLBACK URL: http://localhost:5001/callback")
    print("📊 Test Cases: 4 comprehensive scenarios per language")
    print("⚡ Expected: All test cases should pass with optimal performance")

if __name__ == "__main__":
    main()