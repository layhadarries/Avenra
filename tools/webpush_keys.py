"""Generate private VAPID and subscription-encryption keys outside the repository."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from avenra.services.push_service import generate_keys,PushError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    directory=args.directory.expanduser().resolve()
    root=Path(__file__).resolve().parents[1]
    if directory.is_relative_to(root):parser.error('Choose a private directory outside the Git repository.')
    try:generate_keys(directory)
    except PushError as error:parser.exit(1,'Key generation refused: '+error.code+'\n')
    print('Private keys created outside the repository. Keep this directory backed up and private.')

if __name__=='__main__':main()
