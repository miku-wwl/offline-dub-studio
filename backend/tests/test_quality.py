import hashlib
import importlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest
import soundfile as sf

from app.dialogue import duration_budgets, fit_voice
from app.domain import JobOptions, TemporalMask, TranslationSettings
from app.subtitle_quality import detect_boxes, frame_mask, manual_intervals, redact_video, temporal_restore
from app.translation import translate_with_glossary


@pytest.mark.parametrize('change',[{'start_time':-1},{'end_time':0},{'end_time':.1,'start_time':.2},
    {'width':0},{'x':-1},{'end_time':float('nan')},{'start_time':float('inf')}])
def test_temporal_mask_rejects_invalid_intervals_and_coordinates(change):
    values=dict(start_time=0,end_time=1,x=5,y=5,width=20,height=20)
    with pytest.raises(ValueError):
        TemporalMask(**{**values,**change})


def test_explicit_masks_do_not_depend_on_ocr_and_end_at_the_boundary():
    rows=manual_intervals([dict(start_time=.2,end_time=.6,x=10,y=20,width=30,height=15)],10)
    frame=np.zeros((90,160,3),np.uint8)
    assert not frame_mask(frame,rows,1,10).any()
    assert np.count_nonzero(frame_mask(frame,rows,2,10))==450
    assert not frame_mask(frame,rows,6,10).any()


def test_duration_budget_uses_gaps_and_preserves_source_overlap():
    segments=[{'id':'a','start':0,'end':1},{'id':'b','start':2,'end':4},{'id':'c','start':3,'end':5}]
    budgets=duration_budgets(segments,6)
    assert budgets['a']['available_duration']==2
    assert budgets['b']['available_duration']==2
    assert budgets['b']['source_overlap_seconds']==1


def test_bounded_fitting_accelerates_overlong_speech_and_exports_48k(tmp_path):
    raw=tmp_path/'raw.wav'
    signal=.2*np.sin(np.arange(48000)*2*np.pi*220/24000)
    sf.write(raw,np.concatenate([np.zeros(6000),signal,np.zeros(6000)]),24000)
    result=fit_voice(raw,tmp_path/'fit.wav',1,1.25)
    info=sf.info(tmp_path/'fit.wav')
    assert info.samplerate==48000
    assert result['time_stretch_ratio']==1.25
    assert result['trimmed_leading_silence']>.19
    assert result['speech_samples_discarded']==0
    assert 1.5<info.duration<1.8  # Overflow is preserved and explicitly reported.
    assert result['overflow_duration']>.5


def test_project_glossary_protects_terms_without_sample_rules():
    class Provider:
        def translate(self,text):
            return text.replace('这是','This is ')
    text,provenance=translate_with_glossary(Provider(),'这是自定义名词',{'自定义名词':'custom entity'})
    assert text=='This is custom entity'
    assert provenance['unresolved_terms']==[]
    assert provenance['human_approved'] is False
    with pytest.raises(ValueError):
        TranslationSettings(glossary={'':'invalid'})


def test_missing_glossary_placeholder_is_exposed_for_review():
    class Provider:
        def translate(self,text):
            return 'corrupted placeholder' if 'ZXQ' in text else 'unrelated sentence'
    _text,provenance=translate_with_glossary(Provider(),'名词还有别的内容',{'名词':'entity'})
    assert provenance['placeholder_failures']
    assert provenance['fallback']=='literal-terms-with-all-surrounding-spans'
    assert _text.startswith('entity ')


def test_manual_translation_survives_provider_retry(monkeypatch):
    import sys
    from types import ModuleType,SimpleNamespace
    from app.providers import TranslationProvider
    translation=SimpleNamespace(translate=lambda _text:pytest.fail('Manual translation was replaced'))
    language=SimpleNamespace(code='zh',get_translation=lambda _target:translation)
    module=ModuleType('argostranslate.translate')
    module.get_installed_languages=lambda:[language,SimpleNamespace(code='en')]
    monkeypatch.setitem(sys.modules,'argostranslate.translate',module)
    argos=ModuleType('argostranslate')
    argos.translate=module
    monkeypatch.setitem(sys.modules,'argostranslate',argos)
    segment={'source_text':'名字','translated_text':'Name','short_translation':'Name',
        'translation_provenance':{'manual_override':{'full':'Name'},'source_sha256':hashlib.sha256('名字'.encode()).hexdigest()}}
    TranslationProvider().translate([segment],'zh','en')
    assert segment['translated_text']=='Name'


def test_temporal_reconstruction_preserves_unaffected_pixels():
    background=np.full((90,160,3),160,np.uint8)
    frame=background.copy()
    frame[35:55,60:100]=0
    mask=np.zeros((90,160),np.uint8)
    mask[35:55,60:100]=255
    restored,used=temporal_restore(frame,mask,[(background,np.zeros_like(mask))])
    assert used>0
    assert np.array_equal(restored[mask==0],frame[mask==0])
    assert np.mean(np.abs(restored[mask>0].astype(int)-160))<2


def test_manual_repair_strip_keeps_absent_frames_and_scene_pixels(tmp_path):
    source=tmp_path/'generated.avi'
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'FFV1'),5,(160,90))
    for index in range(15):
        frame=np.full((90,160,3),(40,70,120) if index<8 else (130,80,40),np.uint8)
        cv2.rectangle(frame,(index*7,55),(index*7+12,75),(0,210,90),-1)
        if 5<=index<8:
            cv2.putText(frame,'TEXT',(35,70),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
        writer.write(frame)
    writer.release()
    rows=manual_intervals([dict(start_time=1,end_time=1.6,x=30,y=50,width=90,height=25)],5)
    report=redact_video(source,tmp_path/'strip.mkv',rows,tmp_path/'preview','balanced')
    original=cv2.VideoCapture(str(source))
    strip=cv2.VideoCapture(report['output_video'])
    x,y,w,h=report['patch_roi']
    for index in range(15):
        ok,frame=original.read()
        ok2,patch=strip.read()
        assert ok and ok2
        combined=frame.copy()
        combined[y:y+h,x:x+w]=patch
        mask=frame_mask(frame,rows,index,5)
        assert np.array_equal(combined[mask==0],frame[mask==0])
        if not 5<=index<8:
            assert np.array_equal(combined,frame)
    original.release()
    strip.release()
    assert Path(report['output_video']).stat().st_size<source.stat().st_size*3


def test_outlined_ocr_recall_scene_reset_false_positives_and_cache(tmp_path,monkeypatch):
    font_path=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if not font_path.exists():
        pytest.skip('Noto CJK is required by the Docker/CI image')
    import pytesseract
    font=ImageFont.truetype(str(font_path),32)
    source=tmp_path/'outlined.avi'
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'FFV1'),5,(640,360))
    for index in range(30):
        frame=np.full((360,640,3),(220,220,220) if index<19 else (70,100,50),np.uint8)
        cv2.rectangle(frame,(index*12,300),(index*12+15,330),(0,80,200),-1)
        image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        if 4<=index<9 or 24<=index<29:
            ImageDraw.Draw(image).text((245,292),'你好世界' if index<9 else '这是测试',font=font,
                fill='white',stroke_width=2,stroke_fill='black')
        if 19<=index<22:
            ImageDraw.Draw(image).text((245,292),'LOGO',font=font,fill='white',stroke_width=2,stroke_fill='black')
        writer.write(cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR))
    writer.release()
    rows,_warnings=detect_boxes(source,[(180,280,300,70)],tmp_path/'trace.json')
    assert any(row['start']<=1<row['end'] for row in rows)
    assert any(row['start']<=5<row['end'] for row in rows)
    assert not any(row['start']<=3<row['end'] or row['start']<=4<row['end'] for row in rows)
    monkeypatch.setattr(pytesseract,'image_to_data',lambda *_a,**_k:pytest.fail('Cache was not reused'))
    assert detect_boxes(source,[(180,280,300,70)],tmp_path/'trace.json')[0]==json.loads(json.dumps(rows))
    assert json.loads((tmp_path/'trace.json').read_text())['cache_reused']


def test_fingerprints_invalidate_only_relevant_dependencies(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.pipeline import Pipeline
    config=Settings(data_dir=tmp_path/'data',models_dir=tmp_path/'models')
    config.prepare()
    database=Database(config.db_path)
    database.init()
    work=config.jobs_dir/'new'
    work.mkdir()
    source=work/'source.mp4'
    source.write_bytes(b'immutable fixture')
    options=JobOptions()
    state={'source':source,'work':work,'options':options,'segments':[{'id':'s','start':0,'end':1,'source_text':'名字','translated_text':'Name'}]}
    pipeline=Pipeline(database,lambda:False)
    original={stage:pipeline._fingerprint(stage,state) for stage in ('translate','synthesize','subtitle_processing')}
    options.subtitle_font_size=60
    assert pipeline._fingerprint('synthesize',state)==original['synthesize']
    assert pipeline._fingerprint('subtitle_processing',state)!=original['subtitle_processing']
    options.translation_glossary={'名字':'Name'}
    assert pipeline._fingerprint('translate',state)!=original['translate']
    options.max_speech_speed=1.3
    assert pipeline._fingerprint('synthesize',state)!=original['synthesize']


@pytest.fixture
def quality_api(tmp_path,monkeypatch):
    from app.config import Settings
    from app.db import Database,now
    module=importlib.import_module('app.main')
    config=Settings(data_dir=tmp_path/'data',models_dir=tmp_path/'models')
    config.prepare()
    database=Database(config.db_path)
    database.init()
    monkeypatch.setattr(module,'settings',config)
    monkeypatch.setattr(module,'db',database)
    monkeypatch.setattr(module.manager,'enqueue',lambda _id:None)
    work=config.jobs_dir/'review'
    work.mkdir()
    (work/'inspection.json').write_text(json.dumps({'width':160,'height':90,'duration':6}))
    database.execute('INSERT INTO jobs(id,input_path,display_name,status,stage,created_at,updated_at,options_json) VALUES(?,?,?,?,?,?,?,?)',
        ('review','fixture.mp4','fixture.mp4','awaiting_review','awaiting_review',now(),now(),'{}'))
    for stage in module.STAGES:
        database.execute('INSERT INTO stages(job_id,name,status,progress) VALUES(?,?,?,?)',('review',stage,'completed',100))
    return module,config,database


def test_timed_mask_api_bounds_and_downstream_invalidation(quality_api):
    from fastapi import HTTPException
    api,_config,database=quality_api
    mask=dict(start_time=1,end_time=2,x=10,y=60,width=100,height=20)
    with pytest.raises(HTTPException):
        api.update_temporal_masks('review',api.TemporalMasks(masks=[{**mask,'end_time':7}]))
    with pytest.raises(HTTPException):
        api.update_temporal_masks('review',api.TemporalMasks(masks=[{**mask,'width':200}]))
    api.update_temporal_masks('review',api.TemporalMasks(masks=[mask]))
    job=database.job('review')
    assert job['options']['temporal_masks']==[mask]
    assert all(s['status']==('pending' if s['name'] in ('subtitle_processing','render') else 'completed') for s in job['stages'])


def test_project_glossary_is_snapshotted_for_new_jobs(quality_api,monkeypatch):
    api,config,database=quality_api
    api.update_project_translation(TranslationSettings(glossary={'旗手':'flag bearer'}))
    monkeypatch.setattr(api,'list_packs',lambda:[{'id':p,'ready':True} for p in ['asr-small','translation-zh-en','tts-kokoro-en','separation-htdemucs']])
    from app.db import now
    source=config.inbox_dir/'fixture.mp4'
    source.write_bytes(b'owned generated fixture')
    database.execute('INSERT INTO media(id,path,display_name,bytes,probe_json,created_at) VALUES(?,?,?,?,?,?)',
        ('fixture',str(source),'fixture.mp4',10,json.dumps({'width':160,'height':90,'duration':6}),now()))
    response=api.create_job(api.CreateJob(asset_id='fixture'))
    api.update_project_translation(TranslationSettings(glossary={'旗手':'updated term'}))
    assert database.job(response['id'])['options']['translation_glossary']=={'旗手':'flag bearer'}


def test_translation_edit_records_provenance_and_short_text(quality_api):
    from app.domain import SegmentEdit
    api,config,_database=quality_api
    work=config.jobs_dir/'review'
    original={'id':'s','start':1,'end':2,'source_text':'旗手','translated_text':'flagman','speaker_id':'s1'}
    (work/'transcript.json').write_text(json.dumps({'segments':[original]}))
    api.edit_transcript('review',[SegmentEdit(**{**original,'translated_text':'a flag bearer','short_translation':'flag bearer'})])
    row=json.loads((work/'transcript.json').read_text())['segments'][0]
    assert row['translation_provenance']['manual_override']['previous_text']=='flagman'
    assert row['translation_provenance']['human_approved'] is False
    assert row['short_translation']=='flag bearer'


def test_acceptance_script_protects_evidence_and_counts_collisions(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'scripts'))
    module=importlib.import_module('compare_quality')
    protected=tmp_path/'old-evidence.bin'
    protected.write_bytes(b'previous accepted evidence')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({str(protected):hashlib.sha256(protected.read_bytes()).hexdigest()}))
    assert module.check_protected(manifest)==1
    protected.write_bytes(b'simulated accidental modification')
    with pytest.raises(RuntimeError,match='Protected Phase 2.5'):
        module.check_protected(manifest)
    report=module.collision_metrics({'segments':[
        {'collision_seconds':.2,'unintended_collision_seconds':0,'truncated_seconds':0},
        {'collision_seconds':.01,'unintended_collision_seconds':.01,'truncated_seconds':0},
        {'collision_seconds':.12,'unintended_collision_seconds':.12,'truncated_seconds':0}]})
    assert report['collisions_over_20ms']==2
    assert report['unintended_over_100ms']==1


def test_source_only_edit_requires_retranslation_and_clears_stale_manual_lock(quality_api):
    from app.domain import SegmentEdit
    api,config,database=quality_api
    original={'id':'s','start':1,'end':2,'source_text':'起手','translated_text':'starting hand',
        'speaker_id':'s1','short_translation':None,'translation_provenance':{'manual_override':{'full':'starting hand'}}}
    (config.jobs_dir/'review'/'transcript.json').write_text(json.dumps({'segments':[original]}))
    api.edit_transcript('review',[SegmentEdit(**{**original,'source_text':'旗手'})])
    saved=json.loads((config.jobs_dir/'review'/'transcript.json').read_text())['segments'][0]
    assert not saved['translation_provenance'].get('manual_override')
    job=database.job('review')
    assert next(s for s in job['stages'] if s['name']=='translate')['status']=='pending'
    assert next(s for s in job['stages'] if s['name']=='separate')['status']=='completed'
    assert job['options']['transcript_review_approved'] is False


def test_real_ffmpeg_export_is_48k_stereo_and_limiter_preserves_sample_alignment(tmp_path,monkeypatch):
    import subprocess
    import app.pipeline as module
    from app.config import Settings
    from app.db import Database
    from app.subtitles import write_ass
    config=Settings(data_dir=tmp_path/'data',models_dir=tmp_path/'models')
    config.prepare()
    monkeypatch.setattr(module,'settings',config)
    database=Database(config.db_path)
    database.init()
    work=config.jobs_dir/'generated-render'
    work.mkdir()
    source=work/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=160x90:r=10','-t','2','-c:v','libx264',str(source)],check=True)
    (work/'subtitle-report.json').write_text(json.dumps({'output_video':str(source),'hard_subtitles_processed':False}))
    write_ass([],work/'english-subtitles.ass')
    silence=np.zeros((96000,2),np.float32)
    voice=silence.copy()
    voice[12000:12020]=.2
    sf.write(work/'background.wav',silence,48000)
    sf.write(work/'dub.wav',voice,48000)
    state={'work':work,'source':source,'options':JobOptions(),'probe':{'duration':2}}
    result=module.Pipeline(database,lambda:False)._stage_render(state)
    mixed,rate=sf.read(work/'mixed.wav',always_2d=True)
    assert rate==48000 and mixed.shape[1]==2
    assert np.flatnonzero(np.max(np.abs(mixed),axis=1)>.001)[0]==12000
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',result['video']],text=True))
    audio=next(s for s in info['streams'] if s['codec_type']=='audio')
    assert int(audio['sample_rate'])==48000 and audio['channels']==2


def test_active_manual_mask_crossing_a_scene_cut_never_uses_the_other_scene(tmp_path):
    source=tmp_path/'scene-cut.avi'
    writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'FFV1'),5,(160,90))
    for index in range(12):
        frame=np.full((90,160,3),200 if index<6 else 50,np.uint8)
        if 5<=index<10:
            cv2.rectangle(frame,(50,55),(110,69),(255,255,255),-1)
        writer.write(frame)
    writer.release()
    rows=manual_intervals([dict(start_time=1,end_time=2,x=45,y=50,width=70,height=25)],5)
    report=redact_video(source,tmp_path/'cut-strip.mkv',rows,tmp_path/'preview','balanced')
    strip=cv2.VideoCapture(report['output_video'])
    _x,y,_w,_h=report['patch_roi']
    for index in range(12):
        ok,patch=strip.read()
        assert ok
        if 6<=index<10:
            assert np.mean(np.abs(patch[55-y:69-y,50:110].astype(float)-50))<2
    strip.release()
