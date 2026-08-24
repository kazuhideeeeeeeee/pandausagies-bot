# PANIC STOP

1. Renderのpandausagies serviceを開く。
2. Environmentで`KILL_SWITCH=true`にして保存する。
3. 必要ならCronをSuspendする。
4. 次回run後に`python3 autonomous.py --health`を確認する。
5. `kill_switch: ON`かつrunが`safe_stopped`なら停止完了。

再開は原因を確認した人間だけが行う。`KILL_SWITCH=false`へ戻し、Circuit Breakerが開いていれば明示的なreset commandを実行する。時間経過だけでは再開しない。
