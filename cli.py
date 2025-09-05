"""
Command Line Interface for Pavement Performance Model
"""
import argparse
import model
from model import run_model

# Default values from config
from config import *

def main():
    parser = argparse.ArgumentParser(description='Pavement Performance Model')
    
    # Required inputs
    parser.add_argument('--L', type=float, required=True, help='Road length in km')
    parser.add_argument('--W', type=float, required=True, help='Road width in m')
    parser.add_argument('--h', type=float, required=True, help='Layer thickness in m')
    parser.add_argument('--rho_m', type=float, required=True, help='Mixture density in ton/m³')
    parser.add_argument('--Pb', type=float, required=True, help='Bitumen content (as proportion of total mix weight)')
    parser.add_argument('--Pp', type=float, required=True, help='Plastic content (as proportion of bitumen weight)')
    parser.add_argument('--Pr', type=float, required=True, help='Rubber content (as proportion of bitumen weight)')
    parser.add_argument('--T', type=float, required=True, help='Service temperature in °C')
    parser.add_argument('--A', type=float, required=True, help='Annual ESALs in millions')
    parser.add_argument('--c_agg', type=float, required=True, help='Aggregate cost per ton')
    parser.add_argument('--c_bit', type=float, required=True, help='Bitumen cost per ton')
    parser.add_argument('--c_pl', type=float, required=True, help='Plastic cost per ton')
    parser.add_argument('--c_rub', type=float, required=True, help='Rubber cost per ton')
    parser.add_argument('--overhead', type=float, default=0.0, help='Overhead cost (default: 0)')
    
    args = parser.parse_args()
    
    # Run the model
    results = run_model(
        L=args.L, W=args.W, h=args.h, rho_m=args.rho_m, Pb=args.Pb,
        Pp=args.Pp, Pr=args.Pr, T=args.T, A=args.A,
        c_agg=args.c_agg, c_bit=args.c_bit, c_pl=args.c_pl, c_rub=args.c_rub,
        overhead=args.overhead
    )
    
    # Print results
    print("\nResults:")
    for key, value in results.items():
        print(f"{key}: {value}")

if __name__ == "__main__":
    main()
