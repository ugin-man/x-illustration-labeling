'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const {record,expectedImage,expectedAppearance}=JSON.parse(fs.readFileSync(0,'utf8'));
const code=fs.readFileSync('review_app_v4/app.js','utf8');
const body=code.slice(code.indexOf('function renderLabels()'),code.indexOf('function renderReview()'));
const calls=[];
const element=()=>({append(){},replaceChildren(){}});
vm.runInNewContext(body+';renderLabels();',{
 current:()=>record,imageIndex:0,$:()=>element(),section:element,el:element,detail:element,word:x=>x,
 COLORS:['black','brown','blond_yellow','red','orange','pink','purple','blue','green','white','gray','other'],
 attribute:(field,answer,scope)=>{assert(answer&&answer.status);calls.push({field,scope,status:answer.status});return element();}
});
for(const field of expectedImage)assert(calls.some(c=>c.scope==='image.1'&&c.field===field),'Missing image field '+field);
for(const field of expectedAppearance)assert(calls.some(c=>c.scope==='image.1.c1.appearance1'&&c.field===field),'Missing appearance field '+field);
for(const field of ['character_count','person_count','animal_count','work_form'])assert(calls.some(c=>c.scope==='post'&&c.field===field));
for(const field of ['creation','promotion'])assert(calls.some(c=>c.scope==='context'&&c.field===field));
assert(calls.some(c=>c.field==='environment'&&c.status==='not_applicable'));
assert(calls.some(c=>c.field==='gender_presentation'&&c.status==='unknown'));
console.log('All mandatory image, post, context and appearance fields rendered with their states.');
