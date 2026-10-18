# Preserved first integration rehearsal attempt
The temporary-index rehearsal stopped on Windows long-path handling while reading
an archive snapshot blob via git show. Git also warned about deep untracked
snapshot directory enumeration. No target index, worktree, branch or commit changed.
Corrected tooling uses process-local git -c core.longpaths=true, includes the full
initial preservation inventory, and reads exact blobs through git cat-file.
This failure is not a textual merge conflict or a passing compatibility test.
