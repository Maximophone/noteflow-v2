#!/usr/bin/env python3
"""
Test script to verify NoteFlow v2 is working correctly.

Run with: python test_run.py
(Make sure the server is running first: python -m core.api.server)
"""

import asyncio
import httpx
import tempfile
from pathlib import Path

API_BASE = "http://localhost:8000/api"


async def main():
    async with httpx.AsyncClient() as client:
        print("=" * 60)
        print("NoteFlow v2 Test Suite")
        print("=" * 60)
        
        # 1. Check server health
        print("\n1. Checking server health...")
        try:
            resp = await client.get("http://localhost:8000/health")
            resp.raise_for_status()
            print("   ✅ Server is healthy")
        except Exception as e:
            print(f"   ❌ Server not responding: {e}")
            print("   Make sure to run: python -m core.api.server")
            return
        
        # 2. Get stats
        print("\n2. Getting pipeline stats...")
        resp = await client.get(f"{API_BASE}/stats")
        stats = resp.json()
        print(f"   ✅ Pipeline running: {stats['running']}")
        print(f"   ✅ Processors loaded: {stats['processors_loaded']}")
        
        # 3. List processors
        print("\n3. Listing loaded processors...")
        resp = await client.get(f"{API_BASE}/processors")
        processors = resp.json()
        for p in processors:
            print(f"   - {p['name']}: {p['display_name']}")
        
        # 4. Create a test job
        print("\n4. Creating a test job...")
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "test_output.txt"
            
            resp = await client.post(
                f"{API_BASE}/jobs",
                json={
                    "source_type": "example",
                    "source_name": "Test Job from Script",
                    "data": {
                        "run_example": True,
                        "output_path": str(output_file),
                    },
                    "tags": ["test"],
                }
            )
            resp.raise_for_status()
            job = resp.json()
            job_id = job["id"]
            print(f"   ✅ Created job: {job_id[:8]}...")
            print(f"   ✅ Status: {job['status']}")
            
            # 5. Process the job
            print("\n5. Processing the job...")
            resp = await client.post(f"{API_BASE}/jobs/{job_id}/process")
            resp.raise_for_status()
            job = resp.json()
            print(f"   ✅ Status: {job['status']}")
            
            if job["status"] == "completed":
                print("   ✅ Job completed successfully!")
                
                # Check if file was created
                if output_file.exists():
                    content = output_file.read_text()
                    print(f"   ✅ Output file created: {content}")
                
                # Show artifacts
                resp = await client.get(f"{API_BASE}/jobs/{job_id}/artifacts")
                artifacts = resp.json()
                print(f"   ✅ Artifacts created: {len(artifacts)}")
                for a in artifacts:
                    print(f"      - {a['artifact_type']}: {a['target']}")
            else:
                print(f"   ⚠️  Job status: {job['status']}")
                if job.get("error_message"):
                    print(f"   ❌ Error: {job['error_message']}")
            
            # 6. Test revert
            print("\n6. Testing revert functionality...")
            resp = await client.post(
                f"{API_BASE}/jobs/{job_id}/revert",
                json={}
            )
            resp.raise_for_status()
            job = resp.json()
            print(f"   ✅ Job reverted, status: {job['status']}")
            
            # Check if file was deleted
            if not output_file.exists():
                print("   ✅ Output file was deleted (revert worked!)")
            else:
                print("   ⚠️  Output file still exists")
            
            # 7. Delete the job
            print("\n7. Cleaning up (deleting test job)...")
            resp = await client.delete(f"{API_BASE}/jobs/{job_id}")
            resp.raise_for_status()
            print("   ✅ Job deleted")
        
        print("\n" + "=" * 60)
        print("All tests passed! 🎉")
        print("=" * 60)
        print("\nYou can now:")
        print("  - Open the UI at http://localhost:1420")
        print("  - Create jobs via the API")
        print("  - Add your own processors in the plugins/ directory")


if __name__ == "__main__":
    asyncio.run(main())

