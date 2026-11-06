import argparse
from .subjects import create_master
from .engine import generate
from .model import load_master

def main():
    parser=argparse.ArgumentParser(description='Generate exactly nested, connected laser art from one component master.')
    parser.add_argument('--master',help='Reuse an exported master.json without recreating geometry')
    parser.add_argument('--subject',help='Currently supported: ginkgo leaf (gingko spelling accepted)')
    parser.add_argument('--layers',type=int)
    parser.add_argument('--output',default='outputs/design')
    args=parser.parse_args()
    subject=args.subject or (load_master(args.master).subject if args.master else None) or input('What would you like the master image to represent? ').strip()
    # Subject and layer count are collected sequentially, before geometry exists.
    layers=args.layers
    while layers is None:
        try:
            layers=int(input('How many layers would you like to use to represent it? '))
            if layers<2:
                raise ValueError()
        except ValueError:
            print('Please enter a whole number of at least two.'); layers=None
    try:
        master=load_master(args.master) if args.master else create_master(subject)
        generate(master,layers,args.output)
    except ValueError as error:
        parser.exit(2,f'{error}\n')

if __name__=='__main__':
    main()
