import unreal as u, json, pathlib, traceback, collections, hashlib
ROOT=pathlib.Path(u.Paths.project_dir()).resolve()
REPORT=ROOT/'Saved/StudyReports/rules.json'
REPORT.parent.mkdir(parents=True,exist_ok=True)
result={'checks':[],'failures':[]}
def check(name,condition,detail=''):
    result['checks'].append({'name':name,'passed':bool(condition),'detail':detail})
    if not condition:result['failures'].append(name)
def bfs(walls,start,goal):
    todo=collections.deque([start]);prev={start:None}
    while todo:
        c=todo.popleft()
        if c==goal:
            path=[]
            while c is not None:path.append(c);c=prev[c]
            return path[::-1]
        for d in [-21,1,21,-1]:
            n=c+d
            if n<0 or n>=357 or (d in [-1,1] and n//21!=c//21):continue
            if walls[n]==0 and n not in prev:prev[n]=c;todo.append(n)
    return []
try:
    bp=u.load_asset('/Game/Blueprints/Core/BP_MazeCore')
    a=u.get_default_object(bp.generated_class())
    # 测试作用于内存中的 CDO，finally 恢复全部项目变量，不保存测试状态。
    names=u.BlueprintEditorLibrary.list_member_variable_names(bp,False)
    original={str(k):a.get_editor_property(k) for k in names}
    for k in ['Walls','Explored','Supplies']:original[k]=list(original[k])
    original['Rng']=original['Rng'].copy()
    def get(n):return a.get_editor_property(n)
    def setp(n,v):a.set_editor_property(n,v)
    def run(n,*args):return a.call_method(n,args=args)
    digests=set();all_solvable=True;all_supplies=True;all_border=True;vm_matches=True
    for seed in range(1,51):
        run('ResetRound',seed);w=list(get('Walls'));s=list(get('Supplies'))
        all_solvable &= bool(bfs(w,22,334))
        all_supplies &= sum(s)==12 and not any(w[i] for i in range(357) if s[i])
        all_border &= all(w[i]==1 for i in range(357) if i%21 in [0,20] or i//21 in [0,16])
        vm_matches &= bool(run('CheckPath'))
        digests.add(hashlib.sha256(bytes(w)).hexdigest())
    check('50 个随机种子均有到出口的真实通路',all_solvable)
    check('Blueprint BFS 与独立 Python BFS 结果一致',vm_matches)
    check('每局 12 个补给均位于通路上',all_supplies)
    check('边界完整且不可越界',all_border)
    check('随机种子产生不同布局',len(digests)==50,f'{len(digests)} 个不同布局')
    run('ResetRound',271828);w1=list(get('Walls'));s1=list(get('Supplies'))
    run('ResetRound',271828)
    check('同一随机种子可复现地图和补给',w1==list(get('Walls')) and s1==list(get('Supplies')))
    check('四邻域拒绝跨行穿越',run('NextCell',20,1,1)==-1 and run('NextCell',21,3,1)==-1 and run('NextCell',0,0,1)==-1)
    setp('State',1)
    before=list(get('Walls'));run('TryEdit',22,False);run('TryEdit',334,False);run('TryEdit',0,False)
    check('起点终点和边界拒绝编辑',list(get('Walls'))==before and get('EditCount')==0)
    black=next(i for i in range(357) if 0<i%21<20 and 0<i//21<16 and get('Explored')[i]==0 and abs(i%21-1)+abs(i//21-1)>6 and i!=334)
    run('TryEdit',black,False)
    check('黑色盲区拒绝编辑',list(get('Walls'))==before and '盲区' in str(get('Notice')))
    # Put all terrain into white fog for exhaustive edit transactions.
    setp('Explored',[1]*357);accepted=0;rejected=0;rollback=True
    for cell in range(357):
        if not (0<cell%21<20 and 0<cell//21<16):continue
        setp('EditCooldown',0.0);before=list(get('Walls'));old_count=get('EditCount')
        run('TryEdit',cell,False);after=list(get('Walls'))
        if get('EditCount')>old_count:
            accepted+=1;rollback &= bool(bfs(after,get('PlayerCell'),334))
            # Confirm successful edits invoke cooldown, and a second click is denied.
            again=list(after);run('TryEdit',cell,False);rollback &= again==list(get('Walls'))
        else:
            rejected+=1;rollback &= before==after
    check('遍历所有内部格改墙始终保留出口通路',rollback,f'接受 {accepted} 次，拒绝 {rejected} 次')
    check('至少接受一次合法改墙',accepted>0)
    # Force a one-tile wide legal route so blocking a route tile must roll back.
    corridor=[1]*357
    for x in range(1,20):corridor[21+x]=0
    for y in range(1,16):corridor[y*21+19]=0
    setp('Walls',corridor);setp('Explored',[1]*357);setp('Supplies',[0]*357);setp('PlayerCell',22);setp('EditCooldown',0.0);setp('State',1)
    run('TryEdit',21+7,False)
    check('切断唯一通路的改墙回滚且不消耗冷却',list(get('Walls'))==corridor and get('EditCooldown')==0.0 and '必须保留' in str(get('Notice')))
    for mode in [0,1,2]:
        run('ResetRound',99);setp('State',1);setp('Mode',mode)
        path=bfs(list(get('Walls')),22,334);n=path[1];direction={-21:0,1:1,21:2,-1:3}[n-22]
        setp('Explored',[1]*357);setp('Supplies',[0]*357);run('TryMove',direction)
        check(f'移动模式 {mode} 有独立速度和体力消耗',get('PlayerCell')==n and abs(get('MoveCooldown')-[.27,.16,.095][mode])<1e-5 and abs(get('Stamina')-(100-[.32,.75,1.5][mode]))<1e-5)
    run('ResetRound',42);setp('State',1);setp('Stamina',50.0);setp('Explored',[1]*357)
    path=bfs(list(get('Walls')),22,334);n=path[1];supplies=[0]*357;supplies[n]=1;setp('Supplies',supplies)
    run('TryMove',{-21:0,1:1,21:2,-1:3}[n-22]);check('补给只能拾取一次并恢复体力',get('Supplies')[n]==0 and get('PickupCount')==1 and get('Stamina')>67.0)
    run('ResetRound',17);setp('State',4);setp('Stamina',50.0);setp('EditCooldown',2.5);run('AdvanceRound',1.0)
    check('暂停时计时体力和冷却全部冻结',get('Elapsed')==0 and get('Stamina')==50 and get('EditCooldown')==2.5)
    setp('State',1);setp('Stamina',0.01);setp('RestBudget',0.0);run('AdvanceRound',1.0)
    check('体力耗尽触发操控者获胜',get('State')==3)
    run('ResetRound',18);setp('State',1);w=list(get('Walls'));path=bfs(w,22,334);setp('PlayerCell',path[-2]);setp('MoveCooldown',0.0)
    run('TryMove',{-21:0,1:1,21:2,-1:3}[334-path[-2]])
    check('抵达出口触发闯关者获胜',get('State')==2)
    run('ResetRound',19);setp('State',1);setp('Elapsed',239.99);run('AdvanceRound',0.02)
    check('240 秒救援结束对局',get('State')==2)
    for elapsed,radius in [(0.0,6),(100.0,4),(160.0,3)]:setp('Elapsed',elapsed);check(f'{elapsed:g} 秒的操控者预视野半径',run('PreviewRadius')==radius)
    # No save: CDO mutations are deliberately discarded when the test process exits.
    result['passed']=not result['failures'];result['total']=len(result['checks'])
except Exception:result['fatal']=traceback.format_exc();u.log_error(result['fatal'])
finally:
    if 'original' in globals():
        for k,v in original.items():a.set_editor_property(k,v)
REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
