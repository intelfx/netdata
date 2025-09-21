import time
import random
import string
import sys
from typing import Dict, List
import matplotlib.pyplot as plt

PYTHON_VERSION_STR = "{}.{}".format(sys.version_info.major, sys.version_info.minor)
PYTHON_VERSION_PREFIX = "[{}]".format(PYTHON_VERSION_STR)

def xprint(*args, **kwargs):
    """Wrapper for print() that prefixes output with Python version."""
    print(PYTHON_VERSION_PREFIX, *args, **kwargs)

def generate_random_dict(size: int) -> Dict[str, str]:
    """Generate a random dictionary with string keys and values."""
    return {
        ''.join(random.choice(string.ascii_letters) for _ in range(8)):
            ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
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
    python_version = "{}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)

    xprint("Python version: {}".format(python_version))
    xprint("Dictionary union operator (|) support: {}".format('Yes' if has_union_support else 'No'))
    xprint("=" * 50)

    # Test sizes
    sizes = [10, 100, 1000, 10000, 50000]

    # Number of iterations for each test
    iterations = 1000

    results = {
        'sizes': sizes,
        'unpacking_times': [],
        'union_times': [],
    }

    xprint("Benchmarking dictionary merging methods...")
    xprint("=" * 50)

    for size in sizes:
        xprint("Testing size: {} items per dict".format(size))

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

        xprint("  Unpacking ({} ops): {:.4f}s".format(iterations, unpacking_time))

        # Benchmark union method dict1 | dict2 (only if supported)
        if has_union_support:
            start_time = time.perf_counter()
            for dict1, dict2 in test_dicts:
                result = dict1 | dict2
            union_time = time.perf_counter() - start_time
            results['union_times'].append(union_time)

            xprint("  Union ({} ops):     {:.4f}s".format(iterations, union_time))
            xprint("  Ratio (union/unpacking):      {:.2f}x".format(union_time / unpacking_time))
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
        plt.title('Dictionary Merging Performance Comparison ({} iterations)'.format(iterations))
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
        plt.title('Dictionary Unpacking Performance ({{**d1, **d2}}) - {} iterations'.format(iterations))
        plt.grid(True, alpha=0.3)
        plt.xscale('log')
        plt.yscale('log')

    plt.tight_layout()
    plt.savefig('DictionaryMergeBenchmark.{}.png'.format(PYTHON_VERSION_STR), dpi=150, bbox_inches='tight')
    plt.show()

    # Summary
    xprint("=" * 50)
    xprint("SUMMARY")
    xprint("=" * 50)
    if has_union_support:
        for i, size in enumerate(sizes):
            ratio = results['union_times'][i] / results['unpacking_times'][i]
            faster_method = "Union (|)" if ratio < 1 else "Unpacking ({**})"
            speed_diff = "{:.1f}%".format(abs(1-ratio)*100) if ratio != 1 else "0%"
            xprint("Size {:5d}: {} is faster by {}".format(size, faster_method, speed_diff))
    else:
        xprint("Only unpacking method benchmarked (union operator not supported)")
        for i, size in enumerate(sizes):
            time_per_op = results['unpacking_times'][i] / iterations * 1000
            xprint("Size {:5d}: {:.3f}ms per merge operation".format(size, time_per_op))


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

    xprint("Three dict merge (size={}, {} iterations):".format(size, iterations))
    xprint("  Unpacking: {:.4f}s".format(unpacking_time))

    if has_union_support:
        # Method 2: Chained union
        start_time = time.perf_counter()
        for dict1, dict2, dict3 in test_dicts:
            result = dict1 | dict2 | dict3
        union_time = time.perf_counter() - start_time

        xprint("  Union:     {:.4f}s".format(union_time))
        xprint("  Winner:    {}".format('Union' if union_time < unpacking_time else 'Unpacking'))
    else:
        xprint("  Union operator not available in this Python version")


if __name__ == "__main__":
    # Set random seed for reproducible results
    random.seed(42)
    
    benchmark_dict_merge()
    benchmark_three_dicts()
