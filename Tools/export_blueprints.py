"""导出实际蓝图的函数、变量、节点和引脚；不保存或改写资产。"""
import unreal as u
import json, pathlib, os

root=pathlib.Path(u.Paths.project_dir()).resolve()
target=pathlib.Path(os.environ.get('FOGBOUND_STUDY_REPORT_DIR',str(root/'Saved/StudyReports')))
target.mkdir(parents=True,exist_ok=True)
paths=['/Game/Blueprints/Core/BP_MazeCore','/Game/Blueprints/UI/BP_FogboundHUD','/Game/Blueprints/BP_FogboundMode','/Game/Blueprints/BP_FogboundController']
catalog={'engine':u.SystemLibrary.get_engine_version(),'blueprints':[]}
for path in paths:
    bp=u.load_asset(path);cdo=u.get_default_object(bp.generated_class())
    data={'path':path,'parent':u.BlueprintEditorLibrary.get_blueprint_parent_class(bp).get_path_name(),'variables':[],'graphs':[]}
    for name in u.BlueprintEditorLibrary.list_member_variable_names(bp,False):
        name=str(name)
        typ=u.BlueprintEditorLibrary.get_member_variable_type(bp,name)
        data['variables'].append({'name':name,'type':json.loads(u.BlueprintEditorLibrary.pin_type_to_json_schema(typ,bp.generated_class())),'default':str(cdo.get_editor_property(name))})
    for graph in u.BlueprintEditorLibrary.list_graphs(bp):
        editor=u.BlueprintGraphEditor.get_graph_editor(graph)
        nodes=[]
        for node in editor.list_all_nodes():
            pins=[]
            for pin in node.list_all_pins():
                pins.append({'name':str(pin.get_pin_name()),'direction':str(pin.get_pin_direction()),'type':str(pin.get_pin_type_display_string()),'value':pin.get_pin_value(),'links':[{'node':x.get_owning_node().get_name(),'pin':str(x.get_pin_name())} for x in pin.list_connected_pins()]})
            pos=node.get_node_pos()
            nodes.append({'name':node.get_name(),'title':node.get_node_title(),'class':node.get_class().get_name(),'x':pos.x,'y':pos.y,'pins':pins})
        data['graphs'].append({'name':str(graph.get_fname()),'node_count':len(nodes),'nodes':nodes})
    catalog['blueprints'].append(data)
(target/'blueprint_catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')

bp=u.load_asset(paths[0]);cdo=u.get_default_object(bp.generated_class())
names=u.BlueprintEditorLibrary.list_member_variable_names(bp,False)
original={str(k):cdo.get_editor_property(k) for k in names}
for k in ['Walls','Explored','Supplies']:original[k]=list(original[k])
original['Rng']=original['Rng'].copy()
maps=[]
try:
    for seed in [1,2,3,17,42,99,12345,271828]:
        cdo.call_method('ResetRound',args=(seed,))
        maps.append({'seed':seed,'width':21,'height':17,'start':22,'exit':334,'walls':list(cdo.get_editor_property('Walls')),'supplies':list(cdo.get_editor_property('Supplies')),'explored':list(cdo.get_editor_property('Explored'))})
finally:
    for k,v in original.items():cdo.set_editor_property(k,v)
(target/'ue_seed_samples.json').write_text(json.dumps(maps,ensure_ascii=False,indent=2),encoding='utf-8')
u.log('Fogbound study export complete')
