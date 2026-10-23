from pathlib import Path
import subprocess,sys,argparse
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',default='configs/examples/hvg_research_smoke.yaml');a=p.parse_args();root=Path(__file__).resolve().parents[1]
 r=subprocess.run([sys.executable,'-B',str(root/'scripts/run_full_analysis_pipeline.py'),'--config',a.config],cwd=root);raise SystemExit(r.returncode)
if __name__=='__main__':main()
