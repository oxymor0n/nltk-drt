import nltkfixtemporal

from nltk import load_parser
from nltk.sem.drt import AbstractDrs
from temporaldrt import DRS, DrtApplicationExpression, DrtVariableExpression, unique_variable
import nltk.sem.drt as drt
import temporaldrt
import re
from types import LambdaType

from nltk import LogicParser
from nltk.sem.logic import AndExpression, ParseException
from inference_check import InferenceCheckException, inference_check, get_bk

class local_DrtParser(temporaldrt.DrtParser):
    
    def handle_DRS(self, tok, context):
        drs = drt.DrtParser.handle_DRS(self, tok, context)
        return DRS(drs.refs, drs.conds)

class Tester(object):

    WORD_SPLIT = re.compile(" |, |,")
    EXCLUDED_NEXT = re.compile("^ha[sd]|is|was|not|will$")
    EXCLUDED = re.compile("^does|h?is|red|[a-z]+ness$")
    SUBSTITUTIONS = [
    (re.compile("^died$"), ("did", "die")),
     (re.compile("^([A-Z][a-z]+)'s?$"),   lambda m: (m.group(1), "s")),
     (re.compile("^(?P<stem>[a-z]+)s$"),  lambda m: ("does", m.group("stem"))),
     (re.compile("^([a-z]+(?:[^cvklt]|lk))ed|([a-z]+[cvlkt]e)d$"), lambda m: ("did", m.group(1) if m.group(1) else m.group(2))),
     (re.compile("^([A-Z]?[a-z]+)one$"), lambda m: (m.group(1), "one")),
     (re.compile("^([A-Z]?[a-z]+)thing$"), lambda m: (m.group(1), "thing")),
      (re.compile("^bit$"), ("did", "bite")),
      (re.compile("^bought$"), ("did", "buy")),
      (re.compile("^wrote$"), ("did", "write")),
    ]
    
    def __init__(self, grammar, logic_parser):
        assert isinstance(grammar, str) and grammar.endswith('.fcfg'), \
                            "%s is not a grammar name" % grammar
        self.logic_parser = logic_parser()
        self.parser = load_parser(grammar, logic_parser=self.logic_parser) 

    def _split(self, sentence):
        words = []
        exlude_next = False
        for word in Tester.WORD_SPLIT.split(sentence):
            match = None
            if Tester.EXCLUDED_NEXT.match(word):
                exlude_next = True
                words.append(word)
                continue
            if exlude_next or Tester.EXCLUDED.match(word):
                exlude_next = False
                words.append(word)
                continue
            for pattern, replacement in Tester.SUBSTITUTIONS:
                match = pattern.match(word)
                if match:
                    if isinstance(replacement, LambdaType):
                        words.extend(replacement(match))
                    else:
                        words.extend(replacement)
                    break

            if not match:
                words.append(word)

        return words

    def parse(self, text, **args):
        sentences = text.split('.')
        utter = args.get("utter", True)
        verbose = args.get("verbose", False)
        drs = (utter and self.logic_parser.parse('DRS([n],[])')) or []
        
        for sentence in sentences:
            sentence = sentence.lstrip()
            if sentence:
                words = self._split(sentence)
                if verbose:
                    print words
                trees = self.parser.nbest_parse(words)
                new_drs = trees[0].node['SEM'].simplify()
                if verbose:
                    print(new_drs)
                if drs:
                    drs = (drs + new_drs).simplify()
                else:
                    drs = new_drs
    
        if verbose:
            print drs
        return drs

    def test(self, cases, **args):
        verbose = args.get("verbose", False)
        for number, sentence, expected, error in cases:
            expected_drs = []
            if expected:
                for item in expected if isinstance(expected, list) else [expected]:
                    expected_drs.append(local_DrtParser().parse(item, verbose))
                               
            expression = None
            readings = []
            try:
                expression = self.parse(sentence, **args)
                readings = expression.resolve(verbose)
                
                if error:
                    print("%s. !error: expected %s" % (number, str(error)))
                else:
                    if len(expected_drs) == len(readings):
                        for index, pair in enumerate(zip(expected_drs, readings)):
                            if pair[0] == pair[1]:
                                print("%s. %s reading (%s): %s" % (number, sentence, index, pair[1]))
                    else:
                        print("%s. !comparison failed!\n%s" % (number, sentence))
            except Exception, e:
                if error and isinstance(e, error):
                    print("%s. *%s (%s)" % (number, sentence,  e))
                else:
                    print("%s. !unexpected error: %s" % (number, e))
                    
            
   
    def interpret(self, expr_1, expr_2, bk=False,verbose=False):
        """Interprets a new expression with respect to some previous discourse 
        and background knowledge. The function first generates relevant background
        knowledge and then performs inference check on readings generated by 
        the resolve() method. It returns a list of admissible interpretations in
        the form of DRSs."""
        
        if expr_1 and not isinstance(expr_1, str):
            return "\nDiscourse uninterpretable. Expression %s is not a string" % expr_1
        elif not isinstance(expr_2, str):
            return "\nDiscourse uninterpretable. Expression %s is not a string" % expr_2
        elif bk and not isinstance(bk, dict):
            return "\nDiscourse uninterpretable. Background knowledge is not in dictionary format"
            
        else:
            buffer = self.logic_parser.parse(r'\Q P.(Q+DRS([],[P]))')
            #buffer = parser_obj.parse(r'\Q P.(NEWINFO([],[P])+Q)')
            try:
                try:
                    if expr_1:
                        discourse = self.parse(expr_1, utter=True)
                        
                        expression = self.parse(expr_2, utter=False)
                        
                        for ref in set(expression.get_refs(True)) & set(discourse.get_refs(True)):
                            newref = DrtVariableExpression(unique_variable(ref))
                            expression = expression.replace(ref,newref,True)                   
                        
                        new_discourse = DrtApplicationExpression(DrtApplicationExpression(buffer,discourse),expression).simplify()
                    
                    else: new_discourse = self.parse(expr_2, utter=True)
                                       
                    background_knowledge = None
                    if bk:
                        lp = LogicParser().parse
                        
                        #in order for bk in DRT-language to be parsed without REFER
                        #as this affects inference
                        parser_obj = local_DrtParser()
                        #takes bk in both DRT language and FOL
                        try:
                            for formula in get_bk(new_discourse, bk):
                                if background_knowledge:
                                    try:
                                        background_knowledge = AndExpression(background_knowledge, parser_obj.parse(formula).fol())
                                    except ParseException:
                                        try:
                                            background_knowledge = AndExpression(background_knowledge, lp(formula))
                                        except Exception:
                                            print Exception
                                else:
                                    try:
                                        background_knowledge = parser_obj.parse(formula).fol()
                                    except ParseException:
                                        try:
                                            background_knowledge = lp(formula)
                                        except Exception:
                                            print Exception
                                            
                            if verbose: print "Generated background knowledge:\n%s" % background_knowledge
                        
                        except AssertionError as e:
                            #catches dictionary exceptions 
                            print e
                            
                    interpretations = []
                    
                    index = 1
                    for reading in new_discourse.resolve():
                        print "\nGenerated reading (%s):" % index
                        index = index + 1
                        interpretation = None
                        try:
                            interpretation = inference_check(reading, background_knowledge, verbose)
                        except InferenceCheckException as e:
                            print e.value
                        if interpretation:
                            interpretations.append(interpretation)
                    
                    print "Admissible interpretations:"
                    return interpretations
                    
                except IndexError:
                    print "Input sentences only!"
                
            except ValueError as e:
                print "Error:", e
        
            return "\nDiscourse uninterpretable"                    
                    
                    
    def inference_test(self, cases, bk,verbose=False):
        for number, discourse, expression, judgement in cases:
            print "\n%s. %s, %s --- %s" % (number, discourse, expression, judgement)
            for interpretation in self.interpret(discourse, expression, bk, verbose):
                print interpretation

def main():
    tester = Tester('file:../data/grammar.fcfg', temporaldrt.DrtParser)
    sentences = ["Mia walked", "Angus liked a boy"]
    for sentence in sentences:
        print tester._split(sentence)

if __name__ == '__main__':
    main()