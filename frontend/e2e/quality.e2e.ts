import {expect,test} from '@playwright/test'

test('saves a project glossary and an explicit time-bounded mask',async ({page})=>{
  let glossary:unknown
  let masks:unknown
  const job={id:'quality-fixture',display_name:'generated-quality.mp4',status:'awaiting_review',stage:'awaiting_review',progress:87,
    created_at:'2026-10-24T00:00:00Z',updated_at:'2026-10-24T00:00:00Z',
    options:{subtitle_mode:'balanced',temporal_masks:[]},logs:[],speakers:[],transcript:[],
    stages:[{name:'subtitle_processing',status:'completed',progress:100}],
    subtitle_report:{manual_search_regions:[],regions:[]},media_info:{width:160,height:90,duration:6}}
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname
    if(path.endsWith('/preview-frame') || path.includes('/preview/')) {
      await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#b5c5d5"/></svg>'})
      return
    }
    let body:unknown={}
    if(path==='/api/v1/project/translation') {
      if(route.request().method()==='PUT') glossary=route.request().postDataJSON()
      body={glossary:{}}
    } else if(path.endsWith('/temporal-masks')) {
      masks=route.request().postDataJSON()
      body={id:job.id,status:'queued'}
    } else if(path.endsWith('/jobs')) body={jobs:[job]}
    else if(path.endsWith('/models')) body={packs:[],operations:{}}
    else if(path.endsWith('/inbox')) body={files:[]}
    else if(path.endsWith('/voices')) body={voices:[]}
    else if(path.endsWith('/health')) body={status:'ok'}
    else if(path.endsWith('/diagnostics')) body={cpu_count:8,data_free_bytes:10e9,offline_inference:true}
    else body=job
    await route.fulfill({contentType:'application/json',body:JSON.stringify(body)})
  })
  await page.goto('/')
  await page.getByLabel('Project glossary',{exact:true}).fill('{"旗手":"flag bearer"}')
  await page.getByRole('button',{name:'Save project glossary',exact:true}).click()
  await expect.poll(()=>glossary).toEqual({glossary:{'旗手':'flag bearer'}})
  await page.getByRole('button',{name:/generated-quality.mp4/}).click()
  await page.getByLabel('Mask start (seconds)',{exact:true}).fill('1')
  await page.getByLabel('Mask end (seconds)',{exact:true}).fill('2')
  const image=page.locator('.image-select img')
  await expect.poll(()=>image.evaluate((e:HTMLImageElement)=>e.naturalWidth)).toBe(160)
  await image.scrollIntoViewIfNeeded()
  const rect=(await image.boundingBox())!
  await page.mouse.move(rect.x+rect.width*.2,rect.y+rect.height*.6)
  await page.mouse.down()
  await page.mouse.move(rect.x+rect.width*.8,rect.y+rect.height*.8)
  await page.mouse.up()
  await page.getByRole('button',{name:'Add explicit timed mask',exact:true}).click()
  await expect.poll(()=>masks).toEqual({masks:[{start_time:1,end_time:2,x:32,y:54,width:96,height:18}]})
})
