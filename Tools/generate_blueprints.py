"""Author native Blueprint graphs using UE 5.8's built-in editor API.

This script is an editor-time authoring tool. The resulting game runs entirely
in saved Blueprint assets and has no Python or C++ runtime dependency.
"""
import unreal as u
import json, pathlib, traceback, math, uuid

# 当前正在运行脚本的 UE 工程目录；只在新沙盒中生成资产。
ROOT = pathlib.Path(u.Paths.project_dir()).resolve()
REPORT = ROOT/'Saved/StudyReports/blueprint_generation.json'
REPORT.parent.mkdir(parents=True,exist_ok=True)
B = u.BlueprintEditorLibrary
GE = u.BlueprintGraphEditor
EA = u.EditorAssetLibrary
MATH = '/Script/Engine.KismetMathLibrary.'
ARRAY = '/Script/Engine.KismetArrayLibrary.'
STRING = '/Script/Engine.KismetStringLibrary.'
HUD = '/Script/Engine.HUD.'
PC = '/Script/Engine.PlayerController.'
GP = '/Script/Engine.GameplayStatics.'
CORE = '/Game/Blueprints/Core/BP_MazeCore'
VIEW = '/Game/Blueprints/UI/BP_FogboundHUD'
report = {'compiled':{}, 'graph_counts':{}, 'errors':[]}
TYPES = {t:B.get_basic_type_by_name(t) for t in ['int','real','bool','string']}
TYPES['ints'] = B.get_array_type(TYPES['int'])
TYPES['color'] = B.get_struct_type(u.LinearColor.static_struct())
TYPES['stream'] = B.get_struct_type(u.RandomStream.static_struct())

# 表达式描述器：记录将来需要生成什么蓝图节点，不在 Python 中执行游戏。
class E:
    def __init__(self, kind, typ, *args): self.kind,self.typ,self.args = kind,typ,args
    def __add__(self,b): return op('Add',self,b)
    def __radd__(self,a): return op('Add',a,self)
    def __sub__(self,b): return op('Subtract',self,b)
    def __rsub__(self,a): return op('Subtract',a,self)
    def __mul__(self,b): return op('Multiply',self,b)
    def __rmul__(self,a): return op('Multiply',a,self)
    def __truediv__(self,b): return op('Divide',self,b)
    def __mod__(self,b): return call(ARRAY+'Array_Length','int',TargetArray=self) if b is None else op('Percent',self,b)
    def __lt__(self,b): return op('Less',self,b,'bool')
    def __le__(self,b): return op('LessEqual',self,b,'bool')
    def __gt__(self,b): return op('Greater',self,b,'bool')
    def __ge__(self,b): return op('GreaterEqual',self,b,'bool')
    def eq(self,b): return op('EqualEqual',self,b,'bool')
    def ne(self,b): return op('NotEqual',self,b,'bool')

def val(a):
    if isinstance(a,E): return a
    return E('literal','bool' if isinstance(a,bool) else 'int' if isinstance(a,int) else 'real' if isinstance(a,float) else 'string',a)
def call(path, typ, **kw): return E('call',typ,path,kw)
# UE 的可提升运算节点会由连线推断类型；混合数值运算显式转为 Double。
def op(name,a,b,typ=None):
    a,b = val(a),val(b)
    is_real = 'real' in [a.typ,b.typ]
    if is_real:
        if a.typ=='int':a=call(MATH+'Conv_IntToDouble','real',InInt=a)
        if b.typ=='int':b=call(MATH+'Conv_IntToDouble','real',InInt=b)
    suffix = 'DoubleDouble' if is_real else 'BoolBool' if a.typ=='bool' else 'IntInt'
    if name=='Percent' and is_real: suffix='FloatFloat'
    return call(MATH+name+'_'+suffix,typ or ('real' if is_real else 'int'),A=a,B=b)
def AND(*args):
    x=val(True)
    for a in args: x=call(MATH+'BooleanAND','bool',A=x,B=a)
    return x
def OR(*args):
    x=val(False)
    for a in args:x=call(MATH+'BooleanOR','bool',A=x,B=a)
    return x
def NOT(x):return call(MATH+'Not_PreBool','bool',A=x)
def choose(c,a,b):
    t=val(a).typ
    return call(MATH+{'int':'SelectInt','real':'SelectFloat','string':'SelectString','color':'SelectColor'}[t],t,A=a,B=b,bPickA=c)
def absint(a):return call(MATH+'Abs_Int','int',A=a)
def minimum(a,b):return call(MATH+('FMin' if 'real' in [val(a).typ,val(b).typ] else 'Min'),val(a).typ,A=a,B=b)
def maximum(a,b):return call(MATH+('FMax' if 'real' in [val(a).typ,val(b).typ] else 'Max'),val(a).typ,A=a,B=b)
def clamp(a,lo,hi):return call(MATH+('FClamp' if val(a).typ=='real' else 'Clamp'),val(a).typ,Value=a,Min=lo,Max=hi)
def floor(a):return call(MATH+'FFloor','int',A=a)
def textnum(a):return call(STRING+('Conv_IntToString' if val(a).typ=='int' else 'Conv_DoubleToString'),'string',**({'InInt':a} if val(a).typ=='int' else {'InDouble':a}))
def cat(*args):
    x=val('')
    for a in args:x=call(STRING+'Concat_StrStr','string',A=x,B=a)
    return x
def color(r,g,b,a=1):return E('literal','color',f'(R={r},G={g},B={b},A={a})')
def ink(hex,a=1):
    s=hex.lstrip('#')
    def linear(v):return v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4
    return color(*(linear(int(s[i:i+2],16)/255) for i in (0,2,4)),a)

# Graph 把 Python 中的赋值、分支、循环翻译成保存到 uasset 的 K2 图。
class Graph:
    def __init__(self,bp,name,ins=None,outs=None,create=True):
        self.bp,self.name=bp,name
        self.ed=GE.create_and_edit_function_graph(bp,name) if create else GE.get_graph_editor_by_name(bp,name)
        self.ins={};self.outs=outs or {};self.locals={}; self.pure_counter=0;self.step=0
        if create:
            for k,t in (ins or {}).items():self.ins[k]=E('pin',t,self.ed.add_graph_input_parameter(k,TYPES[t]))
            for k,t in self.outs.items():self.ed.add_graph_output_parameter(k,TYPES[t])
        self.tail=[self.ed.find_graph_entry_pin()] if create else []
    def fork(self,tails):
        g=object.__new__(Graph);g.__dict__=self.__dict__.copy();g.tail=list(tails);return g
    def node(self,n,pure=False):
        if n is None:raise RuntimeError(f'Failed creating node in {self.name}')
        i=self.step; x=400+(i%7)*410;y=(i//7)*1400
        if pure:
            x-=150+(self.pure_counter%3)*250;y+=220+(self.pure_counter%6)*140;self.pure_counter+=1
        else:self.step+=1;self.pure_counter=0
        n.set_node_pos(u.IntPoint(x,y));return n
    def pin(self,n,name,out=False):
        p=n.find_output_pin(name) if out else n.find_input_pin(name)
        if not p.is_valid():raise RuntimeError(f'{self.name}: missing {name} on {n.get_node_title()} pins={[str(p.get_pin_name()) for p in n.list_all_pins()]}')
        return p
    def value(self,e):
        e=val(e)
        if e.kind=='pin':return e.args[0]
        if e.kind=='member':
            n=self.node(self.ed.add_get_member_variable_node(e.args[0]),True)
            return n.find_result_pin()
        if e.kind=='local':
            n=self.node(self.ed.add_get_local_variable_node(e.args[0]),True)
            return n.find_result_pin()
        if e.kind=='call':
            path,kw=e.args;n=self.node(self.ed.add_call_function_node(path),True)
            for k,v in sorted(kw.items(),key=lambda kv:val(kv[1]).kind=='literal'):self.bind(self.pin(n,k),v)
            p=n.find_result_pin()
            if not p.is_valid():
                data=[p for p in n.list_output_pins() if str(p.get_pin_name()) not in ['then']]
                if len(data)!=1:raise RuntimeError(f'{self.name}: ambiguous output {path}')
                p=data[0]
            return p
        raise RuntimeError(f'Unexpected expression {e.kind}')
    # 引脚是代理值；连接依赖明确的输入输出名称。字面量随后写入，避免重建节点时丢失。
    def bind(self,p,e):
        e=val(e)
        if e.kind=='literal':
            x=e.args[0]; s=('true' if x else 'false') if isinstance(x,bool) else str(x)
            if not p.set_pin_value(s):raise RuntimeError(f'{self.name}: failed literal {s} on {p.get_pin_name()}')
        elif not self.value(e).try_create_connection(p):raise RuntimeError(f'{self.name}: cannot connect to {p.get_pin_name()}')
    def chain(self,n):
        exe=n.find_execute_pin()
        if exe.is_valid():
            for t in self.tail:
                if t.is_valid() and not t.try_create_connection(exe):raise RuntimeError(f'{self.name}: cannot connect execution')
            self.tail=[] if n.get_class().get_name() in ['K2Node_FunctionResult','K2Node_MacroInstance'] else [n.find_then_pin()]
        return n
    def local(self,name,t,default=None):
        self.locals[name]=t
        if not self.ed.add_local_variable(name,TYPES[t],'' if default is None else str(default)):raise RuntimeError('local '+name)
        return self.l(name)
    def m(self,name):return E('member',MEMBERS[name],name)
    def l(self,name):return E('local',self.locals[name],name)
    def set(self,name,v,local=False):
        n=self.node(self.ed.add_set_local_variable_node(name) if local else self.ed.add_set_member_variable_node(name))
        self.bind(self.pin(n,name),v);self.chain(n);return self.l(name) if local else self.m(name)
    def sl(self,name,v):return self.set(name,v,True)
    def do(g,path,**kw):
        n=g.node(g.ed.add_call_function_node(path))
        for k,v in sorted(kw.items(),key=lambda kv:val(kv[1]).kind=='literal'):g.bind(g.pin(n,k),v)
        return g.chain(n)
    def own(self,name,**kw):
        return self.do(name,**kw)
    def pure(self,name,typ,**kw):return call(name,typ,**kw)
    def ret(self,**kw):
        n=self.node(self.ed.add_return_node())
        for k,v in kw.items():self.bind(self.pin(n,k),v)
        self.chain(n);self.tail=[]
    def if_(self,c,yes,no=None):
        n=self.node(self.ed.add_branch_node());self.bind(n.find_condition_pin(),c);self.chain(n)
        a=self.fork([n.find_then_pin()]);yes(a)
        b=self.fork([n.find_else_pin()]);
        if no:no(b)
        self.step=max(a.step,b.step)+1;self.pure_counter=0;self.tail=a.tail+b.tail
    def guard(self,c,**ret):self.if_(NOT(c),lambda a:a.ret(**ret))
    # 使用 UE 自带 ForLoop 宏；循环体执行完后宏继续迭代，结束后走 Completed。
    def for_(self,first,last,body):
        n=self.node(self.ed.add_macro_node('/Engine/EditorBlueprintResources/StandardMacros.StandardMacros:ForLoop'))
        self.bind(self.pin(n,'FirstIndex'),first);self.bind(self.pin(n,'LastIndex'),last)
        self.chain(n)
        a=self.fork([self.pin(n,'LoopBody',True)])
        body(a,E('pin','int',self.pin(n,'Index',True)))
        self.step=a.step+1;self.tail=[self.pin(n,'Completed',True)]
    def while_(self,condition,body):
        n=self.node(self.ed.add_macro_node('/Engine/EditorBlueprintResources/StandardMacros.StandardMacros:WhileLoop'))
        self.bind(self.pin(n,'Condition'),condition);self.chain(n)
        a=self.fork([self.pin(n,'LoopBody',True)]);body(a)
        self.step=a.step+1;self.tail=[self.pin(n,'Completed',True)]
    def get(self,arr,idx):return call(ARRAY+'Array_Get','int',TargetArray=arr,Index=idx)
    def length(self,arr):return call(ARRAY+'Array_Length','int',TargetArray=arr)
    def add(self,arr,item):return self.do(ARRAY+'Array_Add',TargetArray=arr,NewItem=item)
    def aset(self,arr,idx,item):return self.do(ARRAY+'Array_Set',TargetArray=arr,Index=idx,Item=item,bSizeToFit=False)
    def clear(self,arr):return self.do(ARRAY+'Array_Clear',TargetArray=arr)
    def random(self,lo,hi):return call(MATH+'RandomIntegerInRangeFromStream','int',Stream=self.m('Rng'),Min=lo,Max=hi)
    def note(self,txt):
        nodes=list(self.ed.list_all_nodes())
        if nodes:
            c=self.ed.add_comment_to_nodes(txt,nodes,90)

MEMBERS={}
def create_bp(path,parent):
    old=EA.load_asset(path)
    if old:raise RuntimeError('Asset already exists; archive the generated asset before rebuilding: '+path)
    bp=B.create_blueprint_asset_with_parent(path,parent)
    if not bp:raise RuntimeError('create '+path)
    return bp
def member(g,name,t,default,category='01 游戏状态'):
    MEMBERS[name]=t
    if not g.ed.add_member_variable(name,TYPES[t],str(default)):raise RuntimeError('member '+name)
    B.set_blueprint_variable_category(g.bp,name,category)
def compile_bp(bp):
    report['stage']='compile '+bp.get_name();REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    ok=B.compile_blueprint(bp);report['compiled'][bp.get_name()]=ok
    if not ok:
        for graph in B.list_graphs(bp):
            ed=GE.get_graph_editor(graph)
            for n in ed.list_nodes_with_errors():report['errors'].append(str(n.get_editor_property('error_msg')))
        raise RuntimeError('Compile failed '+bp.get_name())
    report['stage']='save '+bp.get_name();REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    EA.save_loaded_asset(bp)
    report['stage']='saved '+bp.get_name();REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def fn(bp,name,ins={},outs={},pure=False):
    g=Graph(bp,name,ins,outs)
    if pure:g.ed.set_is_pure_function(True)
    FUNCTIONS[name]=g
    return g
FUNCTIONS={}

# 核心规则保存在 BP_MazeCore；下面依次声明签名，再填充函数体。
def build_core():
    bp=create_bp(CORE,u.HUD)
    g=fn(bp,'NextCell',{'Cell':'int','Direction':'int','Distance':'int'},{'Result':'int'},True)
    initial={
        'GridWidth':('int',21),'GridHeight':('int',17),'StartCell':('int',22),'ExitCell':('int',334),
        'Walls':('ints','()'),'Explored':('ints','()'),'Supplies':('ints','()'),
        'PlayerCell':('int',22),'Seed':('int',0),'Rng':('stream','(InitialSeed=1)'),
        'State':('int',0),'Stamina':('real',100.0),'Elapsed':('real',0.0),'Mode':('int',1),
        'MoveCooldown':('real',0.0),'EditCooldown':('real',0.0),'IdleTime':('real',0.0),
        'RestBudget':('real',12.0),'EditCount':('int',0),'StepCount':('int',0),'RevealCount':('int',0),
        'PickupCount':('int',0),'LastEditCell':('int',-1),'LastEditFlash':('real',0.0),
        'Notice':('string','等待开始'),'NoticeTime':('real',0.0),'ResultDetail':('string',''),
        'WalkInterval':('real',0.27),'RunInterval':('real',0.16),'DashInterval':('real',0.095),
        'WalkCost':('real',0.32),'RunCost':('real',0.75),'DashCost':('real',1.5),
        'WallCooldown':('real',2.8),'SupplyValue':('real',18.0),'ExploreBonus':('real',0.16),
        'PassiveDrain':('real',0.48),'MaxRoundTime':('real',240.0),'SupplyTarget':('int',12),
    }
    for name,(t,d) in initial.items():member(g,name,t,d,'02 平衡参数' if name in ['WalkInterval','RunInterval','DashInterval','WalkCost','RunCost','DashCost','WallCooldown','SupplyValue','ExploreBonus','PassiveDrain','MaxRoundTime','SupplyTarget'] else '01 游戏状态')
    # Declare every signature before resolving Blueprint-to-Blueprint function calls.
    fn(bp,'CellDistance',{'A':'int','B':'int'},{'Result':'int'},True)
    fn(bp,'PreviewRadius',{}, {'Result':'int'},True)
    fn(bp,'MoveInterval',{}, {'Result':'real'},True)
    fn(bp,'MoveCost',{}, {'Result':'real'},True)
    fn(bp,'CheckPath',{}, {'Reachable':'bool'})
    fn(bp,'RevealAroundPlayer')
    fn(bp,'PlaceSupply')
    fn(bp,'ResetRound',{'RequestedSeed':'int'})
    fn(bp,'TryMove',{'Direction':'int'})
    fn(bp,'TryEdit',{'Cell':'int','EraseOnly':'bool'})
    fn(bp,'AdvanceRound',{'Dt':'real'})
    compile_bp(bp)
    # Cardinal neighbour with explicit coordinate bounds prevents row wrap.
    c,d,dist=[g.ins[k] for k in ['Cell','Direction','Distance']]
    x=g.local('X','int');y=g.local('Y','int')
    g.sl('X',c%g.m('GridWidth')+choose(d.eq(1),dist,0)-choose(d.eq(3),dist,0))
    g.sl('Y',c/g.m('GridWidth')+choose(d.eq(2),dist,0)-choose(d.eq(0),dist,0))
    g.ret(Result=choose(AND(x>=0,x<g.m('GridWidth'),y>=0,y<g.m('GridHeight')),y*g.m('GridWidth')+x,-1))
    g.note('四邻域坐标计算 先验证 XY 再生成一维索引 防止跨行穿墙')
    g=FUNCTIONS['CellDistance'];a,b=g.ins['A'],g.ins['B'];w=g.m('GridWidth')
    g.ret(Result=absint(a%w-b%w)+absint(a/w-b/w))
    g=FUNCTIONS['PreviewRadius'];g.ret(Result=choose(g.m('Elapsed')>=150.0,3,choose(g.m('Elapsed')>=90.0,4,6)))
    g=FUNCTIONS['MoveInterval'];g.ret(Result=choose(g.m('Mode').eq(0),g.m('WalkInterval'),choose(g.m('Mode').eq(1),g.m('RunInterval'),g.m('DashInterval'))))
    g=FUNCTIONS['MoveCost'];g.ret(Result=choose(g.m('Mode').eq(0),g.m('WalkCost'),choose(g.m('Mode').eq(1),g.m('RunCost'),g.m('DashCost'))))
    # FIFO 广度优先搜索：Queue + Head 避免每次删除队首；Visited 确保每格最多入队一次。
    g=FUNCTIONS['CheckPath']
    q=g.local('Queue','ints');visited=g.local('Visited','ints');head=g.local('Head','int');cur=g.local('Current','int');nei=g.local('Neighbour','int')
    g.for_(0,g.m('GridWidth')*g.m('GridHeight')-1,lambda a,i:a.add(visited,0))
    g.add(q,g.m('PlayerCell'));g.aset(visited,g.m('PlayerCell'),1);g.sl('Head',0)
    def bfs(a):
        a.sl('Current',a.get(q,head));a.sl('Head',head+1)
        a.if_(cur.eq(a.m('ExitCell')),lambda b:b.ret(Reachable=True))
        def visit(b,d):
            b.sl('Neighbour',b.pure('NextCell','int',Cell=cur,Direction=d,Distance=1))
            def valid(c):
                c.if_(AND(c.get(c.m('Walls'),nei).eq(0),c.get(visited,nei).eq(0)),lambda e:(e.aset(visited,nei,1),e.add(q,nei)))
            b.if_(nei>=0,valid)
        a.for_(0,3,visit)
    g.while_(head<g.length(q),bfs);g.ret(Reachable=False)
    g.note('BFS 队列与访问数组 从闯关者当前位置验证到出口的连通性 最多访问每格一次')
    # 白区是永久数据；灰区是 DrawMap 每帧推导出的临时权限，不能写回 Explored。
    g=FUNCTIONS['RevealAroundPlayer']
    def reveal(a,i):
        def new(b):
            b.aset(b.m('Explored'),i,1);b.set('RevealCount',b.m('RevealCount')+1)
            b.if_(b.get(b.m('Walls'),i).eq(0),lambda c:c.set('Stamina',minimum(100.0,c.m('Stamina')+c.m('ExploreBonus'))))
        a.if_(AND(a.pure('CellDistance','int',A=i,B=a.m('PlayerCell'))<=2,a.get(a.m('Explored'),i).eq(0)),new)
    g.for_(0,g.m('GridWidth')*g.m('GridHeight')-1,reveal);g.ret()
    g.note('白区永久探索 半径二格 只为首次揭示的可走格发放体力奖励')
    # Supply placement scans from a seeded random offset, so placement is bounded.
    g=FUNCTIONS['PlaceSupply'];pos=g.local('Candidate','int');offset=g.local('Offset','int')
    g.sl('Offset',g.random(0,g.m('GridWidth')*g.m('GridHeight')-1))
    def scan(a,i):
        a.sl('Candidate',(i+offset)%(a.m('GridWidth')*a.m('GridHeight')))
        a.if_(AND(a.get(a.m('Walls'),pos).eq(0),a.get(a.m('Supplies'),pos).eq(0),pos.ne(a.m('ExitCell')),a.pure('CellDistance','int',A=pos,B=a.m('PlayerCell'))>=5),lambda b:(b.aset(b.m('Supplies'),pos,1),b.ret()))
    g.for_(0,g.m('GridWidth')*g.m('GridHeight')-1,scan);g.ret()
    # 在奇数坐标房间间做迭代 DFS；每次跨两格，打通中间一格；回路后处理不破坏连通性。
    g=FUNCTIONS['ResetRound'];stack=g.local('Stack','ints');choices=g.local('Candidates','ints');cur=g.local('Current','int');nei=g.local('Neighbour','int');picked=g.local('Picked','int');rnd=g.local('RandomCell','int');s=g.ins['RequestedSeed']
    g.set('Seed',choose(s>0,s,call(MATH+'RandomIntegerInRange','int',Min=1,Max=999999)))
    g.set('Rng',call(MATH+'MakeRandomStream','stream',InitialSeed=g.m('Seed')))
    for name,v in {'State':0,'Stamina':100.0,'Elapsed':0.0,'PlayerCell':22,'Mode':1,'MoveCooldown':0.0,'EditCooldown':0.0,'RestBudget':12.0,'EditCount':0,'StepCount':0,'RevealCount':0,'PickupCount':0,'IdleTime':0.0,'LastEditCell':-1,'LastEditFlash':0.0,'NoticeTime':0.0,'Notice':'探索出口，或用墙体改变对手的选择','ResultDetail':''}.items():g.set(name,v)
    for a in ['Walls','Explored','Supplies']:g.clear(g.m(a))
    g.for_(0,g.m('GridWidth')*g.m('GridHeight')-1,lambda a,i:(a.add(a.m('Walls'),1),a.add(a.m('Explored'),0),a.add(a.m('Supplies'),0)))
    g.aset(g.m('Walls'),g.m('StartCell'),0);g.add(stack,g.m('StartCell'))
    def dfs(a):
        a.sl('Current',a.get(stack,a.length(stack)-1));a.clear(choices)
        def candidate(b,d):
            b.sl('Neighbour',b.pure('NextCell','int',Cell=cur,Direction=d,Distance=2))
            def inbounds(c):
                c.if_(AND(nei%c.m('GridWidth')>0,nei%c.m('GridWidth')<c.m('GridWidth')-1,nei/c.m('GridWidth')>0,nei/c.m('GridWidth')<c.m('GridHeight')-1,c.get(c.m('Walls'),nei).eq(1)),lambda e:e.add(choices,nei))
            b.if_(nei>=0,inbounds)
        a.for_(0,3,candidate)
        def carve(b):
            b.sl('Picked',b.random(0,b.length(choices)-1));b.sl('Neighbour',b.get(choices,picked))
            b.aset(b.m('Walls'),nei,0);b.aset(b.m('Walls'),(cur+nei)/2,0);b.add(stack,nei)
        a.if_(a.length(choices)>0,carve,lambda b:b.do(ARRAY+'Array_Remove',TargetArray=stack,IndexToRemove=b.length(stack)-1))
    g.while_(g.length(stack)>0,dfs)
    def loopcarve(a,i):
        a.sl('RandomCell',a.random(1,19)+21*a.random(1,15))
        hor=AND(a.get(a.m('Walls'),rnd-1).eq(0),a.get(a.m('Walls'),rnd+1).eq(0))
        ver=AND(a.get(a.m('Walls'),rnd-21).eq(0),a.get(a.m('Walls'),rnd+21).eq(0))
        a.if_(AND(a.get(a.m('Walls'),rnd).eq(1),OR(hor,ver)),lambda b:b.aset(b.m('Walls'),rnd,0))
    g.for_(0,45,loopcarve)
    g.for_(1,g.m('SupplyTarget'),lambda a,i:a.own('PlaceSupply'))
    g.own('RevealAroundPlayer');g.set('Stamina',100.0);g.ret()
    g.note('可复现随机种子 迭代 DFS 保证初始连通 少量回路使动态改墙产生路线博弈')
    # Authoritative grid movement and resource costs.
    g=FUNCTIONS['TryMove'];dest=g.local('Destination','int')
    g.guard(AND(g.m('State').eq(1),g.m('MoveCooldown')<=0.0))
    g.sl('Destination',g.pure('NextCell','int',Cell=g.m('PlayerCell'),Direction=g.ins['Direction'],Distance=1));g.guard(dest>=0)
    g.guard(g.get(g.m('Walls'),dest).eq(0))
    g.set('PlayerCell',dest);g.set('StepCount',g.m('StepCount')+1);g.set('IdleTime',0.0)
    g.set('MoveCooldown',g.pure('MoveInterval','real'));g.set('Stamina',maximum(0.0,g.m('Stamina')-g.pure('MoveCost','real')))
    g.own('RevealAroundPlayer')
    def pickup(a):
        a.aset(a.m('Supplies'),dest,0);a.set('Stamina',minimum(100.0,a.m('Stamina')+a.m('SupplyValue')));a.set('PickupCount',a.m('PickupCount')+1)
        a.set('Notice','补给已拾取  体力 +18');a.set('NoticeTime',2.4)
    g.if_(g.get(g.m('Supplies'),dest).eq(1),pickup)
    g.if_(dest.eq(g.m('ExitCell')),lambda a:(a.set('State',2),a.set('ResultDetail','闯关者抵达出口，赢得本局')))
    g.if_(AND(g.m('State').eq(1),g.m('Stamina')<=0.0),lambda a:(a.set('State',3),a.set('ResultDetail','体力耗尽，操控者赢得本局')))
    g.ret();g.note('网格移动真实碰撞 三档速度和消耗 首次探索奖励 补给 出口与体力胜负判定')
    # 改墙事务：先验证权限，再临时修改，BFS 通过才提交；失败还原且不扣冷却。
    g=FUNCTIONS['TryEdit'];cell=g.ins['Cell'];erase=g.ins['EraseOnly'];old=g.local('OldWall','int')
    g.guard(g.m('State').eq(1));g.guard(AND(cell>=0,cell<g.m('GridWidth')*g.m('GridHeight')))
    def reject(a,msg):a.set('Notice',msg);a.set('NoticeTime',2.2);a.ret()
    g.if_(g.m('EditCooldown')>0.0,lambda a:reject(a,'改墙冷却中，请稍候'))
    w=g.m('GridWidth');h=g.m('GridHeight')
    g.if_(OR((cell%w).eq(0),(cell%w).eq(w-1),(cell/w).eq(0),(cell/w).eq(h-1)),lambda a:reject(a,'边界墙不可编辑'))
    g.if_(AND(g.get(g.m('Explored'),cell).eq(0),g.pure('CellDistance','int',A=cell,B=g.m('PlayerCell'))>g.pure('PreviewRadius','int')),lambda a:reject(a,'黑色盲区不可编辑，等待对手探索'))
    g.if_(OR(cell.eq(g.m('StartCell')),cell.eq(g.m('ExitCell')),g.pure('CellDistance','int',A=cell,B=g.m('PlayerCell'))<=1,g.get(g.m('Supplies'),cell).eq(1)),lambda a:reject(a,'起终点、补给与玩家周围一格受保护'))
    g.sl('OldWall',g.get(g.m('Walls'),cell))
    g.if_(AND(erase,old.eq(0)),lambda a:reject(a,'此处已经是通路'))
    g.if_(AND(g.m('Elapsed')>=180.0,old.eq(0)),lambda a:reject(a,'终局阶段仅可拆墙，出口持续开放'))
    g.aset(g.m('Walls'),cell,1-old)
    check=g.own('CheckPath');reachable=E('pin','bool',g.pin(check,'Reachable',True))
    g.if_(NOT(reachable),lambda a:(a.aset(a.m('Walls'),cell,old),reject(a,'改墙被拒绝：必须保留一条到出口的通路')))
    g.set('EditCooldown',choose(g.m('Elapsed')>=120.0,5.0,g.m('WallCooldown')))
    g.set('EditCount',g.m('EditCount')+1);g.set('LastEditCell',cell);g.set('LastEditFlash',1.0)
    g.set('Notice',choose(old.eq(1),'墙体已拆除  通路校验通过','墙体已建立  通路校验通过'));g.set('NoticeTime',2.2);g.ret()
    g.note('改墙事务 盲区与保护格检查 临时改墙 BFS 验证 失败立即还原 成功才消耗冷却')
    # 仅 State=1 推进时间；静止恢复受 RestBudget 限制，后期规则防止无限拖延。
    g=FUNCTIONS['AdvanceRound'];dt=g.ins['Dt'];heal=g.local('RestAmount','real')
    g.guard(g.m('State').eq(1))
    for name in ['MoveCooldown','EditCooldown','NoticeTime','LastEditFlash']:g.set(name,maximum(0.0,g.m(name)-dt))
    g.set('Elapsed',g.m('Elapsed')+dt);g.set('IdleTime',g.m('IdleTime')+dt)
    g.set('Stamina',maximum(0.0,g.m('Stamina')-dt*choose(g.m('Elapsed')>=180.0,0.2,g.m('PassiveDrain'))))
    def rest(a):
        a.sl('RestAmount',minimum(a.m('RestBudget'),dt*0.8));a.set('RestBudget',maximum(0.0,a.m('RestBudget')-heal));a.set('Stamina',minimum(100.0,a.m('Stamina')+heal))
    g.if_(AND(g.m('IdleTime')>0.7,g.m('RestBudget')>0.0,g.m('Stamina')<100.0),rest)
    g.if_(AND(g.m('Mode').eq(0),g.m('IdleTime')<0.4),lambda a:a.set('Stamina',minimum(100.0,a.m('Stamina')+dt*0.12)))
    g.if_(g.m('Stamina')<=0.0,lambda a:(a.set('State',3),a.set('ResultDetail','体力耗尽，操控者赢得本局')))
    g.if_(AND(g.m('State').eq(1),g.m('Elapsed')>=g.m('MaxRoundTime')),lambda a:(a.set('State',2),a.set('ResultDetail','撑过四分钟，救援到达，闯关者获胜')))
    g.ret();g.note('仅对局进行时推进计时 冷却与体力 暂停不扣资源 有限静止恢复 避免无限拖局')
    compile_bp(bp)
    report['graph_counts'][bp.get_name()]={str(gg.get_fname()):len(GE.get_graph_editor(gg).list_all_nodes()) for gg in B.list_graphs(bp)}
    return bp

def prepare_font():
    assets=u.AssetToolsHelpers.get_asset_tools()
    existing=EA.load_asset('/Game/UI/Fonts/FogSans_Font')
    if existing:return existing
    task=u.AssetImportTask();task.filename=str(pathlib.Path(u.Paths.engine_content_dir())/'Slate/Fonts/DroidSansFallback.ttf')
    task.destination_path='/Game/UI/Fonts';task.destination_name='FogSans';task.automated=True;task.save=True
    fac=u.FontFileImportFactory();fac.batch_create_font_asset=u.BatchCreateFontAsset.CREATE_IF_NO_FONT_EXISTS;task.factory=fac
    assets.import_asset_tasks([task])
    for p in EA.list_assets('/Game/UI/Fonts',recursive=True):
        font=EA.load_asset(p)
        if isinstance(font,u.Font):
            font.set_editor_property('legacy_font_size',24);EA.save_loaded_asset(font)
            report['font']=font.get_path_name();return font
    raise RuntimeError('Font import did not create a composite font')

CYAN=ink('67E5DF');AMBER=ink('F7B866');TEXT=ink('E5ECF2');MUTED=ink('8096A7');BORDER=ink('283543')
BG=ink('080D14');PANEL=ink('101922');LIME=ink('BCE686');ROSE=ink('F49BAF')

def rect(g,x,y,w,h,c):return g.own('UIRect',X=x,Y=y,W=w,H=h,Color=c)
def line(g,x,y,x2,y2,c,thickness=1.0):return g.own('UILine',X=x,Y=y,EndX=x2,EndY=y2,Color=c,Thickness=thickness)
def label(g,x,y,txt,size=18.0,c=TEXT):return g.own('UILabel',X=x,Y=y,Text=txt,Size=size,Color=c)
def frame(g,x,y,w,h,c=BORDER):
    rect(g,x,y,w,1.0,c);rect(g,x,y+h-1.0,w,1.0,c);rect(g,x,y,1.0,h,c);rect(g,x+w-1.0,y,1.0,h,c)
def fill_frame(g,x,y,w,h,fill=PANEL,outline=BORDER):rect(g,x,y,w,h,fill);frame(g,x,y,w,h,outline)
def point_in(g,x,y,w,h):return g.pure('PointerIn','bool',X=x,Y=y,W=w,H=h)
# FKey 使用名称文本导入，例如 W 或 SpaceBar；不能写成 (KeyName=W)。
def key(g,name,pressed=False):
    return call(PC+('WasInputKeyJustPressed' if pressed else 'IsInputKeyDown'),'bool',self=call(GP+'GetPlayerController','object',PlayerIndex=0),Key=E('literal','key',name))

# 界面继承规则类。ReceiveDrawHUD 负责输入、更新和 Canvas 绘制；不是 UMG 组件树。
def build_view(core,font):
    bp=create_bp(VIEW,core.generated_class())
    g=fn(bp,'UIRect',{'X':'real','Y':'real','W':'real','H':'real','Color':'color'})
    for name,t,d in [('UIScale','real',1.0),('OffsetX','real',0.0),('OffsetY','real',0.0),('ScreenWidth','real',1440.0),('ScreenHeight','real',900.0),('PointerX','real',0.0),('PointerY','real',0.0),('HoverCell','int',-1),('HelpOpen','bool','false')]:member(g,name,t,d,'03 界面与输入')
    fn(bp,'UILine',{'X':'real','Y':'real','EndX':'real','EndY':'real','Color':'color','Thickness':'real'})
    fn(bp,'UILabel',{'X':'real','Y':'real','Text':'string','Size':'real','Color':'color'})
    fn(bp,'PointerIn',{'X':'real','Y':'real','W':'real','H':'real'},{'Inside':'bool'},True)
    fn(bp,'ClockText',{'Seconds':'int'},{'Text':'string'},True)
    fn(bp,'ProcessInput')
    fn(bp,'DrawShell')
    fn(bp,'DrawMap',{'OriginX':'real','OriginY':'real','ControllerView':'bool'})
    fn(bp,'DrawStatus')
    fn(bp,'DrawModal')
    compile_bp(bp)
    x,y,w,h,c=[g.ins[k] for k in ['X','Y','W','H','Color']]
    g.do(HUD+'DrawRect',RectColor=c,ScreenX=g.m('OffsetX')+x*g.m('UIScale'),ScreenY=g.m('OffsetY')+y*g.m('UIScale'),ScreenW=w*g.m('UIScale'),ScreenH=h*g.m('UIScale'));g.ret()
    g=FUNCTIONS['UILine'];p=g.ins;s=g.m('UIScale')
    g.do(HUD+'DrawLine',StartScreenX=g.m('OffsetX')+p['X']*s,StartScreenY=g.m('OffsetY')+p['Y']*s,EndScreenX=g.m('OffsetX')+p['EndX']*s,EndScreenY=g.m('OffsetY')+p['EndY']*s,LineColor=p['Color'],LineThickness=p['Thickness']*s);g.ret()
    g=FUNCTIONS['UILabel'];p=g.ins;s=g.m('UIScale')
    g.do(HUD+'DrawText',Text=p['Text'],TextColor=p['Color'],ScreenX=g.m('OffsetX')+p['X']*s,ScreenY=g.m('OffsetY')+p['Y']*s,Font=font.get_path_name(),Scale=p['Size']/24.0*s,bScalePosition=False);g.ret()
    g=FUNCTIONS['PointerIn'];p=g.ins
    g.ret(Inside=AND(g.m('PointerX')>=p['X'],g.m('PointerX')<p['X']+p['W'],g.m('PointerY')>=p['Y'],g.m('PointerY')<p['Y']+p['H']))
    g=FUNCTIONS['ClockText'];secs=g.ins['Seconds'];g.ret(Text=cat(textnum(secs/60),':',choose(secs%60<10,'0',''),textnum(secs%60)))
    # Independent keyboard and mouse input routes. No focusable widgets steal WASD.
    g=FUNCTIONS['ProcessInput']
    ctrl=call(GP+'GetPlayerController','object',PlayerIndex=0)
    mouse=g.do(PC+'GetMousePosition',self=ctrl)
    g.set('PointerX',(E('pin','real',g.pin(mouse,'LocationX',True))-g.m('OffsetX'))/g.m('UIScale'))
    g.set('PointerY',(E('pin','real',g.pin(mouse,'LocationY',True))-g.m('OffsetY'))/g.m('UIScale'))
    g.set('HoverCell',-1)
    g.if_(point_in(g,800.0,232.0,546.0,442.0),lambda a:a.set('HoverCell',floor((a.m('PointerX')-800.0)/26.0)+21*floor((a.m('PointerY')-232.0)/26.0)))
    g.if_(key(g,'R',True),lambda a:(a.own('ResetRound',RequestedSeed=0),a.set('HelpOpen',False)))
    def pause(a):
        a.if_(a.m('State').eq(1),lambda b:(b.set('State',4),b.set('HelpOpen',False)),lambda b:b.if_(b.m('State').eq(4),lambda c:(c.set('State',1),c.set('HelpOpen',False))))
    g.if_(OR(key(g,'P',True),key(g,'Escape',True)),pause)
    def help_toggle(a):
        a.set('HelpOpen',NOT(a.m('HelpOpen')))
        a.if_(a.m('State').eq(1),lambda b:b.set('State',4),lambda b:b.if_(AND(b.m('State').eq(4),NOT(b.m('HelpOpen'))),lambda c:c.set('State',1)))
    g.if_(key(g,'F1',True),help_toggle)
    click=key(g,'LeftMouseButton',True)
    def begin(a):
        a.if_(OR(a.m('State').eq(2),a.m('State').eq(3)),lambda b:b.own('ResetRound',RequestedSeed=b.m('Seed')))
        a.set('State',1);a.set('HelpOpen',False)
    g.if_(AND(g.m('State').ne(1),OR(key(g,'SpaceBar',True),key(g,'Enter',True),AND(click,point_in(g,560.0,624.0,320.0,56.0)))),begin)
    g.guard(AND(g.m('State').eq(1),NOT(g.m('HelpOpen'))))
    for i,k in enumerate(['One','Two','Three']):
        g.if_(OR(key(g,k,True),AND(click,point_in(g,54.0+i*210.0,774.0,198.0,66.0))),lambda a,i=i:a.set('Mode',i))
    for d,k,alt in [(0,'W','Up'),(1,'D','Right'),(2,'S','Down'),(3,'A','Left')]:
        g.if_(OR(key(g,k),key(g,alt)),lambda a,d=d:a.own('TryMove',Direction=d))
    g.if_(AND(g.m('HoverCell')>=0,OR(click,key(g,'RightMouseButton',True))),lambda a:a.own('TryEdit',Cell=a.m('HoverCell'),EraseOnly=key(a,'RightMouseButton',True)))
    g.ret();g.note('A 键盘移动与模式切换 B 鼠标编辑 暂停帮助拦截游戏动作 基准画布缩放后反算点击坐标')
    # Main composition: dark tactical table, two visually distinct roles.
    g=FUNCTIONS['DrawShell']
    g.do(HUD+'DrawRect',RectColor=BG,ScreenX=0.0,ScreenY=0.0,ScreenW=g.m('ScreenWidth'),ScreenH=g.m('ScreenHeight'))
    rect(g,36.0,32.0,6.0,38.0,CYAN)
    label(g,54.0,22.0,'FOGBOUND',34.0,TEXT);label(g,338.0,34.0,'雾城博弈',21.0,MUTED)
    label(g,54.0,68.0,'双人非对称迷雾迷宫',14.0,MUTED)
    label(g,1054.0,34.0,cat('SEED  ',textnum(g.m('Seed'))),18.0,MUTED)
    fill_frame(g,1264.0,28.0,128.0,38.0,PANEL,BORDER);label(g,1283.0,36.0,'R  随机换图',15.0,MUTED)
    line(g,36.0,103.0,1404.0,103.0,BORDER)
    # Resource ribbon.
    label(g,54.0,118.0,'体力',17.0,MUTED)
    label(g,111.0,110.0,textnum(floor(g.m('Stamina'))),30.0,CYAN)
    label(g,194.0,126.0,'/ 100',13.0,MUTED)
    rect(g,236.0,124.0,327.0,8.0,ink('22313C'));rect(g,236.0,124.0,g.m('Stamina')*3.27,8.0,CYAN)
    label(g,598.0,118.0,choose(g.m('State').eq(1),'进行中',choose(g.m('State').eq(0),'准备对局',choose(g.m('State').eq(4),'已暂停','本局结束'))),17.0,MUTED)
    label(g,760.0,118.0,'救援倒计时',16.0,MUTED)
    label(g,888.0,111.0,g.pure('ClockText','string',Seconds=maximum(0,240-floor(g.m('Elapsed')))),28.0,TEXT)
    label(g,1090.0,118.0,cat('探索  ',textnum(g.m('RevealCount')*100/357),'%'),17.0,MUTED)
    label(g,1240.0,118.0,cat('步数  ',textnum(g.m('StepCount'))),17.0,MUTED)
    for x,role,num,tag,accent in [(36.0,'迷宫闯关者','A','WASD / 方向键',CYAN),(734.0,'迷宫操控者','B','鼠标左键 / 右键',AMBER)]:
        fill_frame(g,x,162.0,670.0,572.0)
        rect(g,x,162.0,670.0,3.0,accent)
        label(g,x+20.0,178.0,num,24.0,accent);label(g,x+57.0,182.0,role,21.0,TEXT)
        label(g,x+427.0,186.0,tag,15.0,MUTED)
    for x in [82.0,800.0]:
        fill_frame(g,x-8.0,224.0,562.0,458.0,ink('070C12'),BORDER)
    label(g,82.0,696.0,'仅显示已探索区域',15.0,MUTED)
    label(g,800.0,696.0,cat('动态预视野  ',textnum(g.pure('PreviewRadius','int')),' 格'),15.0,MUTED)
    # Small fog legend, shared by both views.
    for x,c,txt in [(360.0,ink('3C626C'),'已探索'),(470.0,ink('414453'),'预视野'),(580.0,ink('080D14'),'盲区')]:
        rect(g,x,698.0,12.0,12.0,c);label(g,x+19.0,695.0,txt,13.0,MUTED)
    label(g,1108.0,696.0,'+ 补给',14.0,LIME);label(g,1224.0,696.0,'◇ 出口',14.0,ROSE)
    g.ret()
    # 同一套 Walls 数据，两个权限视图。补给只在 Known 为真时绘制。
    g=FUNCTIONS['DrawMap'];ox,oy,controller=[g.ins[k] for k in ['OriginX','OriginY','ControllerView']]
    px=g.local('TileX','real');py=g.local('TileY','real');known=g.local('Known','bool');preview=g.local('Preview','bool');wall=g.local('Wall','bool')
    def tile(a,i):
        a.sl('TileX',ox+(i%21)*26.0);a.sl('TileY',oy+(i/21)*26.0)
        a.sl('Known',a.get(a.m('Explored'),i).eq(1))
        a.sl('Preview',AND(controller,a.pure('CellDistance','int',A=i,B=a.m('PlayerCell'))<=a.pure('PreviewRadius','int')))
        a.sl('Wall',a.get(a.m('Walls'),i).eq(1))
        def visible(b):
            def drawwall(c):
                rect(c,px,py,25.0,25.0,choose(known,ink('34515F'),ink('333846')))
                rect(c,px+1.0,py+1.0,23.0,2.0,choose(known,ink('4A6C78'),ink('454B5A')))
                rect(c,px+1.0,py+22.0,23.0,3.0,ink('16212E'))
            def floorfill(c):
                rect(c,px,py,25.0,25.0,choose(known,ink('142B32'),ink('161C27')))
                rect(c,px+11.0,py+11.0,2.0,2.0,choose(known,ink('274750'),ink('242B38')))
            b.if_(wall,drawwall,floorfill)
        a.if_(OR(known,preview),visible,lambda b:rect(b,px,py,25.0,25.0,ink('0B111A')))
        # Known supplies only, for both players.
        def supply(b):
            rect(b,px+6.0,py+6.0,13.0,13.0,ink('263D2A'))
            rect(b,px+10.0,py+7.0,4.0,11.0,LIME);rect(b,px+7.0,py+10.0,10.0,4.0,LIME)
        a.if_(AND(known,a.get(a.m('Supplies'),i).eq(1)),supply)
        def entrance(b):frame(b,px+5.0,py+5.0,15.0,15.0,ink('4B9298'))
        a.if_(i.eq(a.m('StartCell')),entrance)
        def exitmark(b):
            line(b,px+12.0,py+3.0,px+22.0,py+12.0,ROSE,2.0);line(b,px+22.0,py+12.0,px+12.0,py+22.0,ROSE,2.0)
            line(b,px+12.0,py+22.0,px+3.0,py+12.0,ROSE,2.0);line(b,px+3.0,py+12.0,px+12.0,py+3.0,ROSE,2.0)
            rect(b,px+10.0,py+10.0,5.0,5.0,ROSE)
        a.if_(i.eq(a.m('ExitCell')),exitmark)
        def player(b):
            rect(b,px+2.0,py+2.0,22.0,22.0,ink('67E5DF',0.18));frame(b,px+3.0,py+3.0,19.0,19.0,CYAN)
            rect(b,px+8.0,py+8.0,9.0,9.0,TEXT)
            def cart(c):
                rect(c,px+4.0,py+8.0,18.0,10.0,AMBER)
                for wx,wy in [(5.0,5.0),(17.0,5.0),(5.0,18.0),(17.0,18.0)]:rect(c,px+wx,py+wy,4.0,4.0,TEXT)
            b.if_(b.m('Mode').eq(2),cart)
        a.if_(i.eq(a.m('PlayerCell')),player)
        a.if_(AND(i.eq(a.m('LastEditCell')),a.m('LastEditFlash')>0.0,OR(known,preview)),lambda b:frame(b,px,py,25.0,25.0,AMBER))
        a.if_(AND(controller,i.eq(a.m('HoverCell')),a.m('State').eq(1)),lambda b:frame(b,px-1.0,py-1.0,27.0,27.0,AMBER))
    g.for_(0,356,tile);g.ret();g.note('两份地图使用同一权威地形 但分别计算可视权限 预视野只显示地形 不显示补给')
    g=FUNCTIONS['DrawStatus']
    for i,(name,desc,accent) in enumerate([('1  步行','低消耗 · 稳定探索',CYAN),('2  跑步','速度与消耗均衡',CYAN),('3  载具冲刺','极速 · 高体力代价',AMBER)]):
        x=54.0+i*210.0
        fill_frame(g,x,774.0,198.0,66.0,ink('121F29'),BORDER)
        g.if_(g.m('Mode').eq(i),lambda a,x=x,accent=accent:(frame(a,x,774.0,198.0,66.0,accent),rect(a,x,774.0,4.0,66.0,accent)))
        label(g,x+16.0,782.0,name,19.0,TEXT);label(g,x+16.0,813.0,desc,13.0,MUTED)
    label(g,54.0,744.0,'A  移动模式',14.0,MUTED)
    label(g,768.0,744.0,'B  地形编辑',14.0,MUTED)
    fill_frame(g,768.0,774.0,174.0,66.0,ink('211F24'),BORDER)
    label(g,784.0,782.0,choose(g.m('EditCooldown')<=0.0,'改墙已就绪',cat('冷却 ',textnum(floor(g.m('EditCooldown')+1.0)),' 秒')),18.0,AMBER)
    label(g,784.0,813.0,cat('已改墙 ',textnum(g.m('EditCount')),' 次'),13.0,MUTED)
    label(g,966.0,782.0,'左键 增删墙体',18.0,TEXT);label(g,966.0,813.0,'右键 仅拆除墙体',14.0,MUTED)
    label(g,1214.0,782.0,'BFS 保证通路',16.0,AMBER);label(g,1214.0,813.0,'禁止封死出口',14.0,MUTED)
    line(g,36.0,859.0,1404.0,859.0,BORDER)
    label(g,54.0,874.0,choose(g.m('NoticeTime')>0.0,g.m('Notice'),choose(g.m('Elapsed')>=180.0,'终局救援：仅可拆墙，体力流失减缓',choose(g.m('Elapsed')>=120.0,'出口信标增强：改墙冷却延长至 5 秒','探索新格可恢复体力，补给 +18。静止恢复储备有限。'))),14.0,MUTED)
    label(g,1153.0,874.0,'P 暂停    F1 规则    R 换图',14.0,MUTED)
    g.ret()
    # Compact, legible ready/result/help overlays.
    g=FUNCTIONS['DrawModal']
    rect(g,0.0,0.0,1440.0,900.0,ink('050A10',0.88))
    fill_frame(g,300.0,196.0,840.0,514.0,ink('101A25'),ink('425462'))
    rect(g,300.0,196.0,840.0,4.0,CYAN)
    label(g,346.0,227.0,'FOGBOUND  /  雾城博弈',30.0,TEXT)
    def help_panel(a):
        label(a,346.0,281.0,choose(a.m('HelpOpen'),'玩法与规则','对局已暂停'),24.0,CYAN)
        rules=[
            ('A  闯关者','WASD 或方向键移动，1 / 2 / 3 切换步行、跑步与载具冲刺。'),
            ('B  操控者','右侧地图：左键增删墙，右键只拆墙，成功编辑后有冷却。'),
            ('迷雾规则','白区双方已探索；灰区仅 B 预览地形；黑区双方未知，禁止编辑。'),
            ('合法改墙','玩家周围一格、起终点、补给和边界受保护。BFS 拒绝无解改墙。'),
            ('补给与胜负','补给恢复 18 点体力。A 到出口即胜，体力耗尽则 B 胜。'),
            ('对局软化','120 秒后改墙变慢；180 秒后只能拆墙；240 秒救援 A 获胜。'),
        ]
        for i,(head,body) in enumerate(rules):
            label(a,346.0,329.0+i*43.0,head,17.0,AMBER)
            label(a,490.0,330.0+i*43.0,body,13.0,MUTED)
    def ready_result(a):
        heading=choose(a.m('State').eq(0),'一个迷宫，两种视野。',choose(a.m('State').eq(2),'闯关者成功脱离迷雾','操控者赢得了这场博弈'))
        label(a,346.0,282.0,heading,31.0,CYAN)
        a.if_(a.m('State').eq(0),lambda b:label(b,346.0,336.0,'一人探索出口，一人改变路线。每一次选择，都会改变下一步。',18.0,MUTED),lambda b:label(b,346.0,336.0,b.m('ResultDetail'),18.0,MUTED))
        fill_frame(a,346.0,392.0,352.0,162.0,ink('142630'),ink('294750'))
        fill_frame(a,722.0,392.0,372.0,162.0,ink('29242A'),ink('4D4140'))
        label(a,366.0,409.0,'A  /  闯关者',23.0,CYAN)
        label(a,366.0,455.0,'键盘移动，管理体力，找到出口',17.0,TEXT)
        label(a,366.0,494.0,'WASD / 方向键     1 · 2 · 3 切换模式',14.0,MUTED)
        label(a,742.0,409.0,'B  /  操控者',23.0,AMBER)
        label(a,742.0,455.0,'鼠标改墙，拉长路线，消耗对手',17.0,TEXT)
        label(a,742.0,494.0,'左键增删墙体     右键仅拆除',14.0,MUTED)
        a.if_(a.m('State').eq(0),lambda b:label(b,346.0,579.0,'同机双人 · 无需联机 · 双方可在一局结束后交换操作角色',16.0,MUTED),lambda b:label(b,346.0,579.0,cat('耗时 ',b.pure('ClockText','string',Seconds=floor(b.m('Elapsed'))),'     移动 ',textnum(b.m('StepCount')),' 步     改墙 ',textnum(b.m('EditCount')),' 次     补给 ',textnum(b.m('PickupCount')),' 个'),17.0,MUTED))
    g.if_(OR(g.m('HelpOpen'),g.m('State').eq(4)),help_panel,ready_result)
    rect(g,560.0,624.0,320.0,56.0,CYAN)
    label(g,594.0,638.0,choose(g.m('State').eq(0),'空格 / 点击  开始对局',choose(OR(g.m('State').eq(2),g.m('State').eq(3)),'Enter / 点击  同图再战','空格 / 点击  继续对局')),21.0,ink('09232A'))
    label(g,346.0,735.0,'F1  查看规则',16.0,MUTED);label(g,958.0,735.0,'R  重新随机地图',16.0,MUTED)
    g.ret()
    # Events only dispatch to named functions, so graphs remain easy to explain.
    eg=Graph(bp,'EventGraph',create=False)
    begin=B.add_event_override(bp,'ReceiveBeginPlay',u.IntPoint(0,0));eg.tail=[begin.find_then_pin()]
    eg.own('ResetRound',RequestedSeed=0)
    event=B.add_event_override(bp,'ReceiveDrawHUD',u.IntPoint(0,600));eg.tail=[event.find_then_pin()];eg.step=7
    sx=E('pin','int',eg.pin(event,'SizeX',True));sy=E('pin','int',eg.pin(event,'SizeY',True))
    eg.set('ScreenWidth',sx);eg.set('ScreenHeight',sy)
    eg.set('UIScale',minimum(sx/1440.0,sy/900.0))
    eg.set('OffsetX',(eg.m('ScreenWidth')-1440.0*eg.m('UIScale'))/2.0);eg.set('OffsetY',(eg.m('ScreenHeight')-900.0*eg.m('UIScale'))/2.0)
    eg.own('ProcessInput')
    eg.own('AdvanceRound',Dt=clamp(call(GP+'GetWorldDeltaSeconds','real'),0.0,0.05))
    eg.own('DrawShell');eg.own('DrawMap',OriginX=82.0,OriginY=232.0,ControllerView=False);eg.own('DrawMap',OriginX=800.0,OriginY=232.0,ControllerView=True);eg.own('DrawStatus')
    eg.if_(OR(eg.m('State').ne(1),eg.m('HelpOpen')),lambda a:a.own('DrawModal'))
    eg.note('事件只负责调度 输入 更新权威规则 绘制两份独立迷雾视图 最后绘制暂停或结果层')
    compile_bp(bp)
    report['graph_counts'][bp.get_name()]={str(gg.get_fname()):len(GE.get_graph_editor(gg).list_all_nodes()) for gg in B.list_graphs(bp)}
    return bp

def build_level(view):
    controller=EA.load_asset('/Game/Blueprints/BP_FogboundController') or create_bp('/Game/Blueprints/BP_FogboundController',u.PlayerController)
    compile_bp(controller)
    cdo=u.get_default_object(controller.generated_class())
    cdo.set_editor_property('show_mouse_cursor',True)
    cdo.set_editor_property('enable_click_events',True)
    cdo.set_editor_property('enable_mouse_over_events',True)
    EA.save_loaded_asset(controller)
    mode=EA.load_asset('/Game/Blueprints/BP_FogboundMode') or create_bp('/Game/Blueprints/BP_FogboundMode',u.GameModeBase)
    compile_bp(mode)
    cdo=u.get_default_object(mode.generated_class());cdo.set_editor_property('hud_class',view.generated_class());cdo.set_editor_property('player_controller_class',controller.generated_class());cdo.set_editor_property('default_pawn_class',None)
    EA.save_loaded_asset(mode)
    levels=u.get_editor_subsystem(u.LevelEditorSubsystem)
    if EA.does_asset_exist('/Game/Maps/L_Fogbound'):
        report['map']='/Game/Maps/L_Fogbound';return
    levels.new_level('/Game/Maps/L_Fogbound')
    actors=u.get_editor_subsystem(u.EditorActorSubsystem)
    info=actors.spawn_actor_from_class(u.TextRenderActor,u.Vector(0,0,150),u.Rotator(0,180,0))
    info.set_actor_label('FOGBOUND — Press Play')
    comp=info.get_component_by_class(u.TextRenderComponent);comp.set_text('FOGBOUND\nPress Play to start\nBlueprint-only local two player maze');comp.set_world_size(35)
    levels.save_current_level()
    report['map']='/Game/Maps/L_Fogbound'

def main():
    # 保护学习者手工修改过的正式工程。生成器只接受缺少 HUD 的全新沙盒。
    if EA.does_asset_exist(VIEW):
        raise RuntimeError('The HUD already exists. Use Tools/Run-Generate.ps1 to create a fresh sandbox.')
    core=EA.load_asset(CORE)
    if core:
        for name in B.list_member_variable_names(core,False):
            schema=json.loads(B.pin_type_to_json_schema(B.get_member_variable_type(core,name),core.generated_class()))
            MEMBERS[str(name)]='stream' if str(name)=='Rng' else {'integer':'int','number':'real','boolean':'bool','string':'string','array':'ints'}[schema['type']]
        report['compiled'][core.get_name()]=B.compile_blueprint(core)
        report['graph_counts'][core.get_name()]={str(gg.get_fname()):len(GE.get_graph_editor(gg).list_all_nodes()) for gg in B.list_graphs(core)}
    else:core=build_core()
    # Exercise the saved Blueprint VM in an editor world before authoring the UI.
    actor=u.get_default_object(core.generated_class())
    original={k:actor.get_editor_property(k) for k in MEMBERS}
    for k in ['Walls','Explored','Supplies']:original[k]=list(original[k])
    original['Rng']=original['Rng'].copy()
    actor.call_method('ResetRound',args=(12345,))
    report['smoke']={'walls':len(actor.get_editor_property('Walls')),'path':actor.call_method('CheckPath'),'player':actor.get_editor_property('PlayerCell')}
    for k,v in original.items():actor.set_editor_property(k,v)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    EA.save_loaded_asset(core)
    font=prepare_font()
    view=build_view(core,font)
    build_level(view)
    report['success']=True

try:
    main()
except Exception:
    report['fatal']=traceback.format_exc();u.log_error(report['fatal'])
    raise
finally:
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
