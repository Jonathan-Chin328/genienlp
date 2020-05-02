import logging
from typing import List
from transformers import GPT2Config, GPT2LMHeadModel, GPT2Tokenizer
import torch

class GPT2Seq2Seq(GPT2LMHeadModel):
    def __init__(self, config):
        super().__init__(config)
    
    def set_token_ids(self, end_token_id, sep_token_id, pad_token_id):
        self.end_token_id = end_token_id
        self.sep_token_id = sep_token_id
        self.pad_token_id = pad_token_id
        logging.info('end_token_id = %s', self.end_token_id)
        logging.info('sep_token_id = %s', self.sep_token_id)
        logging.info('pad_token_id = %s', self.pad_token_id)

    def pad_to_max_length(self, input_sequences: List[List[int]]):
        """
        Adds pad tokens before the sep_token
        """
        max_length = max([len(s) for s in input_sequences])
        copy_input_sequences = []
        for i in range(len(input_sequences)):
            sep_token_index = input_sequences[i].index(self.sep_token_id)
            copy_input_sequences.append(input_sequences[i][:sep_token_index] + \
                                        [self.pad_token_id]*(max_length-len(input_sequences[i])) +\
                                        input_sequences[i][sep_token_index:])
        
        return copy_input_sequences

    
    def enforce_repetition_penalty_(self, lprobs, batch_size, num_beams, prev_output_tokens, repetition_penalty):
        """ repetition penalty from CTRL (https://arxiv.org/abs/1909.05858), but much faster on GPU
        """
        if repetition_penalty == 1.0:
            return lprobs
        m = torch.scatter(input=torch.zeros_like(lprobs), dim=1, index=prev_output_tokens, value=1)
        m[:self.sep_token_id] = 0
        m[:self.pad_token_id] = 0
        # logger.info('m = ', m.shape)
        need_change = m * lprobs
        need_divide = need_change > 0
        need_multiply = need_change < 0
        lprobs = need_divide * lprobs / repetition_penalty + need_multiply * lprobs * repetition_penalty + (1-m) * lprobs
        
        # old, slow implementation
        # if repetition_penalty != 1.0:
            # for i in range(context.shape[0]):
                # for previous_token in set(generated[i].tolist()):
                    # if lprobs[i, previous_token] > 0:
                        # lprobs[i, previous_token] /= repetition_penalty
                    # else:
                        # lprobs[i, previous_token] *= repetition_penalty

    def generate(self, **kwargs):
        outputs = super().generate(**kwargs)
        outputs = outputs[:, :].tolist()
        for i in range(len(outputs)):
            outputs[i] = [x for x in outputs[i] if x != self.pad_token_id] # remove padding
            outputs[i] = outputs[i][outputs[i].index(self.sep_token_id)+1:] # only return the output (i.e. after sep_token)

        return outputs


    def prepare_inputs_for_generation(self, input_ids, past, **kwargs):
        sep_token_position = (input_ids==self.sep_token_id).to(torch.long)
        # for i, s in enumerate(sep_token_position):
        #     if torch.sum(s) != 1:
        #         print(i, s)
        #         print(input_ids[i])
        #         exit()
        assert (torch.sum(sep_token_position, dim=1)==1).all(), 'All input_ids must contain exactly one start_token. sep_token_position = %s\nsep_token_id = %d' % (str(sep_token_position), self.sep_token_id)
        token_type_ids = torch.cumsum(sep_token_position, dim=1) - sep_token_position
        attention_mask = (input_ids!=self.pad_token_id).to(torch.long) # 0 means mask, 1 means no mask
        position_ids = (torch.cumsum(attention_mask, dim=1)-1)*(1-token_type_ids)+(torch.cumsum(token_type_ids, dim=1)-1)*token_type_ids
        token_type_ids = self.sep_token_id * (1-token_type_ids) + self.end_token_id * token_type_ids
        # print('input_ids = ', input_ids)
        # print('position_ids = ', position_ids)
        # print('token_type_ids = ', token_type_ids)
        # print('attention_mask = ', attention_mask)
        if past:
            input_ids = input_ids[:, -1].unsqueeze(-1)
            position_ids = position_ids[:, -1].unsqueeze(-1)
            token_type_ids = token_type_ids[:, -1].unsqueeze(-1)
            attention_mask = attention_mask[:, -1].unsqueeze(-1)

        inputs = {"input_ids": input_ids, "position_ids": position_ids, "token_type_ids": token_type_ids, "attention_mask": attention_mask, "past": past}
        return inputs