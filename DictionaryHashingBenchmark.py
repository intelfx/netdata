
import time
import random
import string
from typing import Dict, List

def generate_test_dict(size: int, key_length: int = 10, value_length: int = 20) -> Dict[str, str]:
    """Generate a dictionary with random string keys and values."""
    result = {}
    for _ in range(size):
        key = ''.join(random.choices(string.ascii_letters + string.digits, k=key_length))
        value = ''.join(random.choices(string.ascii_letters + string.digits, k=value_length))
        result[key] = value
    return result

def hash_tuple(target: Dict[str, str]) -> int:
    """Hash dictionary using tuple of items."""
    return hash(tuple(target.items()))

def hash_frozenset(target: Dict[str, str]) -> int:
    """Hash dictionary using frozenset of items."""
    return hash(frozenset(target.items()))

def benchmark_method(method, test_dicts: List[Dict[str, str]], method_name: str) -> float:
    """Benchmark a hashing method and return average time per operation."""
    start_time = time.perf_counter()
    
    for target_dict in test_dicts:
        method(target_dict)
    
    end_time = time.perf_counter()
    total_time = end_time - start_time
    avg_time = total_time / len(test_dicts)
    
    print(f"{method_name:20s}: {total_time:.6f}s total, {avg_time*1000000:.2f}μs avg")
    return total_time

def run_benchmark():
    """Run the complete benchmark comparing both hashing methods."""
    print("Python Dictionary Hashing Benchmark")
    print("=" * 50)
    
    # Test configurations: (dict_size, num_tests)
    test_configs = [
        (5, 10000),
        (10, 10000),
        (25, 10000),
        (50, 10000),
        (100, 10000),
    ]
    
    for dict_size, num_tests in test_configs:
        print(f"\nDictionary size: {dict_size} items, Number of tests: {num_tests}")
        print("-" * 60)
        
        # Generate test data
        test_dicts = [generate_test_dict(dict_size) for _ in range(num_tests)]
        
        # Benchmark tuple method
        time_tuple = benchmark_method(hash_tuple, test_dicts, "Sorted Tuple")
        
        # Benchmark frozenset method
        time_frozenset = benchmark_method(hash_frozenset, test_dicts, "Frozenset")
        
        # Calculate speedup
        if time_frozenset > 0:
            speedup = time_tuple / time_frozenset
            faster_method = "Frozenset" if speedup > 1 else "Tuple"
            speedup_factor = max(speedup, 1/speedup)
            print(f"Result: {faster_method} is {speedup_factor:.2f}x faster")
        
        # Verify both methods produce consistent results (though hashes may differ)
        sample_dict = test_dicts[0]
        hash1 = hash_tuple(sample_dict)
        hash2 = hash_tuple(sample_dict)
        hash3 = hash_frozenset(sample_dict)
        hash4 = hash_frozenset(sample_dict)
        
        print(f"Consistency check: Sorted tuple: {hash1 == hash2}, Frozenset: {hash3 == hash4}")

if __name__ == "__main__":
    # Set random seed for reproducible results
    random.seed(42)
    
    run_benchmark()
    
    print("\n" + "=" * 50)
    print("Benchmark Summary:")
    print("- Tuple: hash(tuple(target.items()))")
    print("- Frozenset: hash(frozenset(target.items()))")
    print("- Both methods produce consistent hashes for the same dictionary")
    print("- Performance may vary based on dictionary size and key distribution")
