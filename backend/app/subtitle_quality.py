"""CPU subtitle-line detection and bounded, scene-local restoration."""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

from .subtitles import active_boxes, _inpaint_roi


VERSION='outlined-lines-glyph-temporal-v26.3'


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source,'sha256').hexdigest()


def outlined_glyphs(frame, search):
    """White islands surrounded by dark outline, grouped into complete lines."""
    height,width=frame.shape[:2]
    result=np.zeros((height,width),np.uint8)
    boxes=[]
    for rx,ry,rw,rh in search:
        x0,y0=max(0,rx),max(0,ry)
        x1,y1=min(width,rx+rw),min(height,ry+rh)
        crop=frame[y0:y1,x0:x1]
        if not crop.size:
            continue
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        neutral=np.max(crop,axis=2).astype(int)-np.min(crop,axis=2).astype(int)<65
        white=((gray>180)&neutral).astype(np.uint8)*255
        # Dark outlines remain separable when white glyph interiors touch a
        # white shirt. Horizontal projection removes long vertical subject edges.
        ink=((gray<135)&(cv2.dilate(white,np.ones((11,11),np.uint8))>0)).astype(np.uint8)*255
        density=np.count_nonzero(ink,axis=1)
        threshold=max(18,float(density.max(initial=0))*.43)
        band=(density>=threshold).astype(np.uint8).reshape(-1,1)
        band=cv2.morphologyEx(band,cv2.MORPH_CLOSE,np.ones((9,1),np.uint8))
        for region in cv2.findContours(band,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            _bx,by,_bw,bh=cv2.boundingRect(region)
            if bh<12:
                continue
            top,bottom=max(0,by-4),min(gray.shape[0],by+bh+4)
            section=ink[top:bottom]
            grouped=cv2.dilate(section,np.ones((3,17),np.uint8))
            contours,_=cv2.findContours(grouped,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x,y,w,h=cv2.boundingRect(contour)
                if h<12 or w<max(36,h*1.1) or h>=rh*.95:
                    continue
                y+=top
                boxes.append((x+x0,y+y0,w,h))
                character=cv2.morphologyEx(ink[y:y+h,x:x+w],cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
                filled=np.zeros_like(character)
                for shape in cv2.findContours(character,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
                    cv2.drawContours(filled,[shape],-1,255,-1)
                expanded=cv2.dilate(filled,np.ones((7,7),np.uint8))
                result[y+y0:y+y0+h,x+x0:x+x0+w]|=expanded
    return result,boxes


def _scene_thumb(frame):
    return cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(64,36))


def scene_changed(left,right):
    return float(np.mean(cv2.absdiff(left,right)))>32


def detect_boxes(source:Path, manual:list, trace:Path, checkpoint=None, progress=None):
    signature=digest(source)
    cache={}
    try:
        cache=json.loads(trace.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        pass
    if cache.get('version')==VERSION and cache.get('source_sha256')==signature and cache.get('manual_search_regions')==[list(x) for x in manual]:
        cache['cache_reused']=True
        trace.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf-8')
        return cache['intervals'],cache['warnings']
    import pytesseract
    from pytesseract import Output
    cap=cv2.VideoCapture(str(source))
    fps=cap.get(cv2.CAP_PROP_FPS) or 25
    width,height=int(cap.get(3)),int(cap.get(4))
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    search=manual or [(round(width*.12),round(height*.84),round(width*.76),round(height*.14))]
    rows=[]
    anchors=[]
    scenes=[]
    frame_no=0
    previous=None
    old=os.environ.get('OMP_THREAD_LIMIT')
    os.environ['OMP_THREAD_LIMIT']='1'
    try:
        while True:
            if checkpoint:
                checkpoint()
            ok,frame=cap.read()
            if not ok:
                break
            thumb=_scene_thumb(frame)
            cut=previous is not None and scene_changed(previous,thumb)
            if cut:
                anchors=[]
                scenes.append(frame_no)
            previous=thumb
            _glyph,candidates=outlined_glyphs(frame,search)
            # OCR only when anchors expire or a line changes. CV still confirms
            # glyph presence on every frame; tracking never fills absent frames.
            accepted=[]
            for x,y,w,h in candidates:
                if not any(rx+rw*.15<=x+w/2<=rx+rw*.85 for rx,_ry,rw,_rh in search):
                    continue
                signature_pixels=cv2.resize((cv2.cvtColor(frame[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY)<135).astype(np.float32),(64,16))
                nearby=next((a for a in anchors if abs(a['box'][1]-y)<h*.4 and abs(a['box'][0]-x)<max(20,w*.15) and abs(a['box'][2]-w)<max(25,w*.2)),None)
                if nearby and float(np.mean(np.abs(signature_pixels-nearby['pixels'])))>.18:
                    nearby=None
                if not nearby or frame_no-nearby['frame']>round(fps*.4):
                    crop=frame[max(0,y-3):min(height,y+h+3),max(0,x-3):min(width,x+w+3)]
                    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
                    data=pytesseract.image_to_data(cv2.threshold(gray,180,255,cv2.THRESH_BINARY_INV)[1],
                        lang='chi_sim+eng',config='--psm 7',output_type=Output.DICT)
                    text=''.join(str(t) for t,c in zip(data['text'],data['conf']) if float(c)>=10)
                    nearby={'box':(x,y,w,h),'frame':frame_no,'text':text,'pixels':signature_pixels,
                        'chinese':sum('\u3400'<=c<='\u9fff' for c in text)>=2}
                    anchors=[a for a in anchors if abs(a['box'][1]-y)>h*.4]+[nearby]
                if not nearby['chinese']:
                    continue
                accepted.append((max(0,x-3),max(0,y-3),min(width-x+3,w+6),min(height-y+3,h+6)))
            if accepted:
                rows.append({'start':frame_no/fps,'end':(frame_no+1)/fps,'start_frame':frame_no,'end_frame':frame_no+1,'boxes':accepted,'kind':'automatic-glyph-line'})
            frame_no+=1
            if progress and frame_no%25==0:
                progress(frame_no,total)
    finally:
        cap.release()
        if old is None:
            os.environ.pop('OMP_THREAD_LIMIT',None)
        else:
            os.environ['OMP_THREAD_LIMIT']=old
    warnings=['Chinese line recall and reconstruction still require visual review.']
    trace.write_text(json.dumps({'version':VERSION,'source_sha256':signature,'manual_search_regions':manual,
        'intervals':rows,'scene_boundaries':scenes,'warnings':warnings,'cache_reused':False},ensure_ascii=False,indent=2),encoding='utf-8')
    return rows,warnings


def manual_intervals(masks:list, fps:float) -> list[dict]:
    return [{'start':m['start_time'],'end':m['end_time'],'start_frame':math.ceil(m['start_time']*fps-1e-8),
        'end_frame':math.ceil(m['end_time']*fps-1e-8),'boxes':[(m['x'],m['y'],m['width'],m['height'])],
        'kind':'explicit-manual'} for m in masks]


def frame_mask(frame, regions, frame_no, fps):
    mask=np.zeros(frame.shape[:2],np.uint8)
    for row in regions:
        boxes=active_boxes([row],frame_no,fps)
        if not boxes:
            continue
        if row.get('kind')=='explicit-manual':
            for x,y,w,h in boxes:
                mask[y:y+h,x:x+w]=255
        else:
            glyph,_=outlined_glyphs(frame,boxes)
            mask=cv2.bitwise_or(mask,glyph)
    return mask


def temporal_restore(frame, mask, references):
    """Use only scene-local, unoccluded, photometrically consistent references.

    Flow is calculated on a padded subtitle crop. Unsupported pixels fall back
    to spatial inpainting, with the original retained outside the exact mask.
    """
    spatial=_inpaint_roi(frame,mask,3,cv2.INPAINT_TELEA)
    # Smooth near-vertical surfaces (clothing, poles, wall gradients) benefit
    # from aligned boundary interpolation instead of a large Telea smear.
    ys,xs=np.where(mask>0)
    if len(xs):
        top,bottom=max(0,int(ys.min())-1),min(frame.shape[0]-1,int(ys.max())+1)
        if bottom>top:
            for column in np.unique(xs):
                a=frame[max(0,top-2):top+1,column].mean(axis=0)
                b=frame[bottom:bottom+3,column].mean(axis=0)
                if np.linalg.norm(a-b)>100:
                    continue
                rows=np.flatnonzero(mask[:,column])
                alpha=np.clip((rows-top)/(bottom-top),0,1)[:,None]
                spatial[rows,column]=(a[None]*(1-alpha)+b[None]*alpha).astype(np.uint8)
    if not references:
        return spatial,0
    y,x=np.where(mask>0)
    x0,x1=max(0,x.min()-24),min(frame.shape[1],x.max()+25)
    y0,y1=max(0,y.min()-20),min(frame.shape[0],y.max()+21)
    target=frame[y0:y1,x0:x1]
    target_gray=cv2.cvtColor(target,cv2.COLOR_BGR2GRAY)
    hole=mask[y0:y1,x0:x1]>0
    candidates=[]
    for reference,reference_mask in references:
        src=reference[y0:y1,x0:x1]
        src_gray=cv2.cvtColor(src,cv2.COLOR_BGR2GRAY)
        # Motion estimation uses filled glyphs so the text itself cannot drive flow.
        a=cv2.inpaint(target_gray,(hole*255).astype(np.uint8),3,cv2.INPAINT_TELEA)
        b=cv2.inpaint(src_gray,reference_mask[y0:y1,x0:x1],3,cv2.INPAINT_TELEA)
        flow=cv2.calcOpticalFlowFarneback(a,b,None,.5,2,15,2,5,1.1,0)
        grid_x,grid_y=np.meshgrid(np.arange(src.shape[1],dtype=np.float32),np.arange(src.shape[0],dtype=np.float32))
        mx,my=grid_x+flow[:,:,0],grid_y+flow[:,:,1]
        warped=cv2.remap(src,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
        unavailable=cv2.remap(reference_mask[y0:y1,x0:x1],mx,my,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=255)>0
        known=(~hole).astype(np.float32)
        support=cv2.blur(known,(41,41))
        error=cv2.blur(np.abs(warped.astype(np.float32)-target.astype(np.float32)).mean(axis=2)*known,(41,41))/np.maximum(support,.05)
        valid=hole&(~unavailable)&(error<18)&(support>.08)&(np.linalg.norm(flow,axis=2)<24)
        candidates.append((warped,valid))
    restored=spatial.copy()
    count=np.zeros(hole.shape,np.float32)
    colors=np.zeros(target.shape,np.float32)
    for image,valid in candidates:
        colors+=image*valid[:,:,None]
        count+=valid
    use=count>0
    patch=restored[y0:y1,x0:x1]
    patch[use]=(colors[use]/count[use,None]).astype(np.uint8)
    restored[mask==0]=frame[mask==0]
    return restored,int(np.count_nonzero(use))


def redact_video(source:Path,destination:Path,regions:list,preview_dir:Path,mode='balanced',checkpoint=None,progress=None):
    cap=cv2.VideoCapture(str(source))
    width,height=int(cap.get(3)),int(cap.get(4))
    fps=cap.get(cv2.CAP_PROP_FPS) or 25
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    preview_dir.mkdir(exist_ok=True,parents=True)
    if not regions:
        ok,first=cap.read()
        cap.release()
        if ok:
            for name in ('original','mask','repaired'):
                cv2.imwrite(str(preview_dir/f'subtitle-{name}.png'),first)
        return {'width':width,'height':height,'fps':fps,'frames_processed':0,'masked_frames':0,'unmasked_frames':0,
            'regions':[],'mask_applied':False,'output_video':str(source),'technique':VERSION,'patch_roi':None}
    all_boxes=[b for row in regions for b in row['boxes']]
    y0=max(0,min(b[1] for b in all_boxes)-20)//2*2
    y1=min(height,math.ceil((max(b[1]+b[3] for b in all_boxes)+20)/2)*2)
    # Only the lossless subtitle strip is stored; rendering overlays it onto the
    # original decode. No second lossy encode and no full-frame FFV1 storage.
    destination=destination.with_suffix('.mkv')
    writer=cv2.VideoWriter(str(destination),cv2.VideoWriter_fourcc(*'FFV1'),fps,(width,y1-y0))
    if not writer.isOpened():
        raise RuntimeError('Cannot open subtitle strip writer')
    reference_cap=cv2.VideoCapture(str(source))
    bank=deque()
    lookahead=max(2,round(fps*2))
    reference_index=0
    reference_scene=0
    reference_previous=None
    frame_no=0
    masked=temporal_pixels=0
    previous=None
    scene=0
    preview=False
    try:
        # Two sequential decoders and a four-second bank of sampled subtitle
        # strips keep memory independent of movie duration.
        while True:
            ok,frame=cap.read()
            if not ok:
                break
            while reference_index<=frame_no+lookahead:
                ref_ok,reference=reference_cap.read()
                if not ref_ok:
                    break
                reference_thumb=_scene_thumb(reference)
                if reference_previous is not None and scene_changed(reference_previous,reference_thumb):
                    reference_scene+=1
                reference_previous=reference_thumb
                if reference_index%max(1,round(fps*.2))==0:
                    ref_mask,ref_boxes=outlined_glyphs(reference,[(0,y0,width,y1-y0)])
                    # A reference must be text-free at the replacement pixel.
                    # Whole detected line bounds are excluded conservatively,
                    # even though the actual repair uses smaller glyph masks.
                    for x,y,w,h in ref_boxes:
                        ref_mask[max(0,y-4):min(height,y+h+4),max(0,x-4):min(width,x+w+4)]=255
                    for row in regions:
                        if row.get('kind')=='explicit-manual':
                            for x,y,w,h in active_boxes([row],reference_index,fps):
                                ref_mask[y:y+h,x:x+w]=255
                    bank.append((reference_index,reference[y0:y1].copy(),ref_mask[y0:y1].copy(),reference_scene))
                reference_index+=1
            while bank and bank[0][0]<frame_no-lookahead:
                bank.popleft()
            if checkpoint:
                checkpoint()
            thumb=_scene_thumb(frame)
            if previous is not None and scene_changed(previous,thumb):
                scene+=1
            previous=thumb
            mask=frame_mask(frame,regions,frame_no,fps)
            crop=frame[y0:y1]
            crop_mask=mask[y0:y1]
            if mask.any():
                candidates=[(i,ref,rm) for i,ref,rm,rs in bank if rs==scene and abs(i-frame_no)>1]
                candidates.sort(key=lambda r:np.count_nonzero((crop_mask>0)&(r[2]==0))/(1+abs(r[0]-frame_no)*.01),reverse=True)
                references=[(ref,rm) for _i,ref,rm in candidates[:8]]
                clean_crop,used=temporal_restore(crop,crop_mask,references) if mode=='balanced' else (_inpaint_roi(crop,crop_mask,3,cv2.INPAINT_TELEA),0)
                temporal_pixels+=used
                masked+=1
                if not preview:
                    marked=frame.copy()
                    marked[mask>0]=(0,0,255)
                    clean=frame.copy()
                    clean[y0:y1]=clean_crop
                    for name,image in [('original',frame),('mask',marked),('repaired',clean)]:
                        cv2.imwrite(str(preview_dir/f'subtitle-{name}.png'),image)
                    preview=True
            else:
                clean_crop=crop
            writer.write(clean_crop)
            frame_no+=1
            if progress and frame_no%25==0:
                progress(frame_no,total)
    finally:
        cap.release()
        reference_cap.release()
        writer.release()
    return {'width':width,'height':height,'fps':fps,'frames_processed':frame_no,'masked_frames':masked,
        'unmasked_frames':frame_no-masked,'regions':regions,'mask_applied':bool(masked),
        'output_video':str(destination),'technique':VERSION,'patch_roi':[0,y0,width,y1-y0],
        'temporal_reconstructed_pixels':temporal_pixels,'spatial_fallback':'aligned-boundaries-and-glyph-telea',
        'quality_review_required':True}
