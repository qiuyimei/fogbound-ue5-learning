import unreal as u, json, pathlib
root=pathlib.Path(u.Paths.project_dir()).resolve()
report_path=root/'Saved/StudyReports/assets.json'
report_path.parent.mkdir(parents=True,exist_ok=True)
report={}
for path in ['/Game/Blueprints/Core/BP_MazeCore','/Game/Blueprints/UI/BP_FogboundHUD','/Game/Blueprints/BP_FogboundController','/Game/Blueprints/BP_FogboundMode']:
    bp=u.load_asset(path)
    ok=u.BlueprintEditorLibrary.compile_blueprint(bp)
    report[path]={'compiled':ok,'warnings':[],'errors':[]}
    for graph in u.BlueprintEditorLibrary.list_graphs(bp):
        ed=u.BlueprintGraphEditor.get_graph_editor(graph)
        for n in ed.list_nodes_with_errors():report[path]['errors'].append(str(n.get_editor_property('error_msg')))
        for n in ed.list_nodes_with_warnings():report[path]['warnings'].append(str(n.get_editor_property('error_msg')))
    u.EditorAssetLibrary.save_loaded_asset(bp,False)
report['mode_defaults']={}
cdo=u.get_default_object(u.load_class(None,'/Game/Blueprints/BP_FogboundMode.BP_FogboundMode_C'))
for name in ['hud_class','player_controller_class','default_pawn_class']:
    v=cdo.get_editor_property(name);report['mode_defaults'][name]=v.get_path_name() if v else None
ui=u.load_asset('/Game/Blueprints/UI/BP_FogboundHUD');view=u.get_default_object(ui.generated_class())
report['ui_checks']={'clock_0':view.call_method('ClockText',args=(0,))=='0:00','clock_239':view.call_method('ClockText',args=(239,))=='3:59','preview_radius':view.call_method('PreviewRadius')==6,'nonzero_divisors':True,'key_literals':True}
for graph in u.BlueprintEditorLibrary.list_graphs(ui):
    for node in u.BlueprintGraphEditor.get_graph_editor(graph).list_all_nodes():
        if ' / ' in node.get_node_title():
            pin=node.find_input_pin('B')
            if pin.is_valid() and not pin.list_connected_pins():
                try: valid=float(pin.get_pin_value())!=0
                except:valid=False
                if not valid:report['ui_checks']['nonzero_divisors']=False
        key_pin=node.find_input_pin('Key')
        if key_pin.is_valid():
            value=key_pin.get_pin_value()
            if not value or value.startswith('('):report['ui_checks']['key_literals']=False
original_pointer=(view.get_editor_property('PointerX'),view.get_editor_property('PointerY'))
view.set_editor_property('PointerX',810.0);view.set_editor_property('PointerY',242.0)
report['ui_checks']['pointer_inside']=bool(view.call_method('PointerIn',args=(800.,232.,546.,442.)))
report['ui_checks']['pointer_outside']=not bool(view.call_method('PointerIn',args=(0.,0.,50.,50.)))
view.set_editor_property('PointerX',original_pointer[0]);view.set_editor_property('PointerY',original_pointer[1])
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
