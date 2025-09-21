import time
import random
import string
import sys
from typing import Dict, List
import matplotlib.pyplot as plt

PYTHON_VERSION_STR = f"{sys.version_info.major}.{sys.version_info.minor}"
PYTHON_VERSION_PREFIX = f"[{PYTHON_VERSION_STR}]"

def xprint(*args, **kwargs):
    """Wrapper for print() that prefixes output with Python version."""
    print(PYTHON_VERSION_STR, *args, **kwargs)

def generate_random_dict(size: int) -> Dict[str, str]:
    """Generate a random dictionary with string keys and values."""
    return {
        ''.join(random.choices(string.ascii_letters, k=8)):
        ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        for _ in range(size)
    }

def supports_dict_union() -> bool:
    """Check if the current Python version supports dictionary union operator."""
    try:
        _ = {} | {}
    except TypeError:
        return False
    return True

def benchmark_dict_merge():
    """Benchmark dictionary merging methods across different sizes."""

    # Check Python version compatibility
    has_union_support = supports_dict_union()
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    xprint(f"Python version: {python_version}")
    xprint(f"Dictionary union operator (|) support: {'Yes' if has_union_support else 'No'}")
    xprint("=" * 50)

    # Test sizes
    sizes = [10, 100, 1000, 10000, 50000]

    # Number of iterations for each test
    iterations = 1000

    results = {
        'sizes': sizes,
        'unpacking_times': [],
        'union_times': [] if has_union_support else None
    }

    xprint("Benchmarking dictionary merging methods...")
    xprint("=" * 50)

    for size in sizes:
        xprint(f"Testing size: {size} items per dict")

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
        results['unpacking_times'].append(unpacking_time)

        xprint(f"  Unpacking ({iterations} ops): {unpacking_time:.4f}s")

        # Benchmark union method dict1 | dict2 (only if supported)
        if has_union_support:
            start_time = time.perf_counter()
            for dict1, dict2 in test_dicts:
                result = dict1 | dict2
            union_time = time.perf_counter() - start_time
            results['union_times'].append(union_time)

            xprint(f"  Union ({iterations} ops):     {union_time:.4f}s")
            xprint(f"  Ratio (union/unpacking):      {union_time / unpacking_time:.2f}x")
        else:
            xprint("  Union operator not available in this Python version")

        xprint()

    # Plot results
    if has_union_support:
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
    else:
        # Plot only unpacking performance
        plt.figure(figsize=(10, 6))
        plt.plot(sizes, results['unpacking_times'], 'b-o', linewidth=2, markersize=8)
        plt.xlabel('Dictionary Size (items per dict)')
        plt.ylabel('Time (seconds)')
        plt.title(f'Dictionary Unpacking Performance ({{**d1, **d2}}) - {iterations} iterations')
        plt.grid(True, alpha=0.3)
        plt.xscale('log')
        plt.yscale('log')

    plt.tight_layout()
    plt.savefig(f'DictionaryMergeBenchmark.{PYTHON_VERSION_STR}.png', dpi=150, bbox_inches='tight')
    plt.show()

    # Summary
    xprint("=" * 50)
    xprint("SUMMARY")
    xprint("=" * 50)
    if has_union_support:
        for i, size in enumerate(sizes):
            ratio = results['union_times'][i] / results['unpacking_times'][i]
            faster_method = "Union (|)" if ratio < 1 else "Unpacking ({**})"
            speed_diff = f"{abs(1-ratio)*100:.1f}%" if ratio != 1 else "0%"
            xprint(f"Size {size:5d}: {faster_method} is faster by {speed_diff}")
    else:
        xprint("Only unpacking method benchmarked (union operator not supported)")
        for i, size in enumerate(sizes):
            time_per_op = results['unpacking_times'][i] / iterations * 1000
            xprint(f"Size {size:5d}: {time_per_op:.3f}ms per merge operation")


def benchmark_three_dicts():
    """Benchmark merging three dictionaries."""
    has_union_support = supports_dict_union()

    xprint("\n" + "=" * 50)
    xprint("BONUS: Three Dictionary Merge")
    xprint("=" * 50)

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

    xprint(f"Three dict merge (size={size}, {iterations} iterations):")
    xprint(f"  Unpacking: {unpacking_time:.4f}s")

    if has_union_support:
        # Method 2: Chained union
        start_time = time.perf_counter()
        for dict1, dict2, dict3 in test_dicts:
            result = dict1 | dict2 | dict3
        union_time = time.perf_counter() - start_time

        xprint(f"  Union:     {union_time:.4f}s")
        xprint(f"  Winner:    {'Union' if union_time < unpacking_time else 'Unpacking'}")
    else:
        xprint("  Union operator not available in this Python version")


if __name__ == "__main__":
    # Set random seed for reproducible results
    random.seed(42)
    
    benchmark_dict_merge()
    benchmark_three_dicts()
