import sys
import time
import random
import string
from typing import Dict, List
import matplotlib.pyplot as plt

def generate_random_dict(size: int) -> Dict[str, str]:
    """Generate a random dictionary with string keys and values."""
    return {
        ''.join(random.choices(string.ascii_letters, k=8)): 
        ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        for _ in range(size)
    }

def xprint(fmt, *args, **kwargs):
    """Print to stdout and flush."""
    print(fmt, *args, **kwargs)
    sys.stdout.flush()

def benchmark_dict_merge():
    """Benchmark dictionary merging methods across different sizes."""
    
    # Test sizes
    sizes = [10, 100, 1000, 10000, 50000]
    
    # Number of iterations for each test
    iterations = 1000
    
    results = {
        'sizes': sizes,
        'unpacking_times': [],
        'union_times': []
    }
    
    print("Benchmarking dictionary merging methods...")
    print("=" * 50)
    
    for size in sizes:
        print(f"Testing size: {size} items per dict")
        
        # Generate test data
        test_dicts = [
            [generate_random_dict(size), generate_random_dict(size)] 
            for _ in range(iterations)
        ]
        
        # Benchmark unpacking method {**dict1, **dict2}
        start_time = time.perf_counter()
        for dict1, dict2 in test_dicts:
            result = {**dict1, **dict2}
        unpacking_time = time.perf_counter() - start_time
        
        # Benchmark union method dict1 | dict2
        start_time = time.perf_counter()
        for dict1, dict2 in test_dicts:
            result = dict1 | dict2
        union_time = time.perf_counter() - start_time
        
        results['unpacking_times'].append(unpacking_time)
        results['union_times'].append(union_time)
        
        print(f"  Unpacking ({iterations} ops): {unpacking_time:.4f}s")
        print(f"  Union ({iterations} ops):     {union_time:.4f}s")
        print(f"  Ratio (union/unpacking):      {union_time/unpacking_time:.2f}x")
        print()
    
    # Plot results
    plt.figure(figsize=(12, 8))
    
    # Performance comparison
    plt.subplot(2, 1, 1)
    plt.plot(sizes, results['unpacking_times'], 'b-o', label='Unpacking {**d1, **d2}', linewidth=2)
    plt.plot(sizes, results['union_times'], 'r-s', label='Union d1 | d2', linewidth=2)
    plt.xlabel('Dictionary Size (items per dict)')
    plt.ylabel('Time (seconds)')
    plt.title(f'Dictionary Merging Performance Comparison ({iterations} iterations)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xscale('log')
    plt.yscale('log')
    
    # Ratio plot
    plt.subplot(2, 1, 2)
    ratios = [union/unpacking for union, unpacking in zip(results['union_times'], results['unpacking_times'])]
    plt.plot(sizes, ratios, 'g-^', linewidth=2, markersize=8)
    plt.axhline(y=1, color='k', linestyle='--', alpha=0.5, label='Equal performance')
    plt.xlabel('Dictionary Size (items per dict)')
    plt.ylabel('Performance Ratio (Union / Unpacking)')
    plt.title('Relative Performance (values < 1 mean union is faster)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xscale('log')
    
    plt.tight_layout()
    plt.savefig('dict_merge_benchmark.png', dpi=150, bbox_inches='tight')
    plt.show()
    
    # Summary
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for i, size in enumerate(sizes):
        ratio = results['union_times'][i] / results['unpacking_times'][i]
        faster_method = "Union (|)" if ratio < 1 else "Unpacking ({**})"
        speed_diff = f"{abs(1-ratio)*100:.1f}%" if ratio != 1 else "0%"
        print(f"Size {size:5d}: {faster_method} is faster by {speed_diff}")

def benchmark_three_dicts():
    """Benchmark merging three dictionaries."""
    print("\n" + "=" * 50)
    print("BONUS: Three Dictionary Merge Comparison")
    print("=" * 50)
    
    size = 1000
    iterations = 1000
    
    # Generate test data
    test_dicts = [
        [generate_random_dict(size), generate_random_dict(size), generate_random_dict(size)]
        for _ in range(iterations)
    ]
    
    # Method 1: Unpacking
    start_time = time.perf_counter()
    for dict1, dict2, dict3 in test_dicts:
        result = {**dict1, **dict2, **dict3}
    unpacking_time = time.perf_counter() - start_time
    
    # Method 2: Chained union
    start_time = time.perf_counter()
    for dict1, dict2, dict3 in test_dicts:
        result = dict1 | dict2 | dict3
    union_time = time.perf_counter() - start_time
    
    print(f"Three dict merge (size={size}, {iterations} iterations):")
    print(f"  Unpacking: {unpacking_time:.4f}s")
    print(f"  Union:     {union_time:.4f}s")
    print(f"  Winner:    {'Union' if union_time < unpacking_time else 'Unpacking'}")

if __name__ == "__main__":
    # Set random seed for reproducible results
    random.seed(42)
    
    benchmark_dict_merge()
    benchmark_three_dicts()
